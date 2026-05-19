/**
 * components/intelligence/IntelligenceLayout.tsx — 3-column intelligence page shell
 * (PLAN-0074 Wave H T-H-02)
 *
 * WHY THIS COMPONENT EXISTS:
 * The intelligence page has four content areas:
 *   1. Column 1 (25%): Knowledge graph panel — Cytoscape graph explorer
 *   2. Column 2 (45%): Intelligence panel — Relations/Evidence/Paths/Narratives tabs
 *   3. Column 3 (30%): Entity sidebar — health score, current narrative, key metrics
 *   4. Full-width row: Collapsible entity chat panel
 *
 * WHY CSS GRID (not flexbox):
 * The 3-column layout requires precise proportional widths (25/45/30%) that
 * also resize correctly when the user drags panel handles. CSS Grid's
 * `grid-template-columns` expresses this constraint directly and handles
 * fractional resizing without JavaScript. Flexbox would require explicit
 * flex-basis on each child, which gets complicated with resize handles.
 *
 * WHY REACT-RESIZABLE-PANELS (not custom drag):
 * `react-resizable-panels` is already in package.json (v4.10.0) and handles
 * keyboard resize, ARIA labelling, and pointer capture correctly across
 * browsers. Custom drag implementations routinely miss edge cases (double-tap,
 * touch, keyboard resize, min/max constraints). Using the battle-tested
 * library keeps the panel code focused on layout, not drag mechanics.
 *
 * WHY MOBILE TABS (<1280px):
 * Three side-by-side panels require ~1280px to be usable. Below that width,
 * each panel becomes too narrow for its content. Collapsing to 4 tabs
 * (Graph/Intelligence/Sidebar/Chat) gives each panel the full viewport on
 * mobile/small screens without sacrificing information density on desktop.
 *
 * WHO USES IT: app/intelligence/[entity_id]/page.tsx
 */

"use client";
// WHY "use client": uses useState for chat panel toggle and reads the
// SelectedEntityContext which requires client-side rendering.

import { type ReactNode } from "react";
import {
  Panel,
  Group,
  Separator,
} from "react-resizable-panels";
// WHY Group/Separator (not PanelGroup/PanelResizeHandle):
// react-resizable-panels v4.x renamed the exports:
//   PanelGroup → Group
//   PanelResizeHandle → Separator
// These are the correct v4.10.0 export names.
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { SelectedEntityProvider } from "@/contexts/SelectedEntityContext";
// WHY GraphDepthProvider here: GraphPanel (col-1) and EntitySidebar (col-3) are
// siblings — both need the same depth so EntitySidebar's query key matches the
// cache primed by GraphPanel. Context is simpler than lifting state to page.tsx.
import { GraphDepthProvider } from "@/contexts/GraphDepthContext";

// ── Props ─────────────────────────────────────────────────────────────────────

interface IntelligenceLayoutProps {
  /** Entity UUIDv7 from the URL param — the "anchor" entity for this page */
  entityId: string;
  /** Column 1 content: graph panel */
  graphPanel: ReactNode;
  /** Column 2 content: intelligence tabs */
  intelligencePanel: ReactNode;
  /** Column 3 content: entity sidebar */
  sidebarPanel: ReactNode;
  /** Full-width bottom row: entity chat */
  chatPanel: ReactNode;
}

// ── Component ─────────────────────────────────────────────────────────────────

export function IntelligenceLayout({
  entityId,
  graphPanel,
  intelligencePanel,
  sidebarPanel,
  chatPanel,
}: IntelligenceLayoutProps) {
  return (
    // SelectedEntityProvider wraps the entire layout so all three panels
    // share the same selectedEntityId / anchorEntityId without prop drilling.
    // WHY here (not in the page): the provider must wrap all three panels
    // simultaneously so they can all react to the same selection event.
    //
    // WHY key={entityId} on SelectedEntityProvider (FR-3.1 CRIT-008):
    // When navigating /intelligence/A → /intelligence/B, React may keep the
    // component tree mounted if it shares a layout. key={entityId} forces a
    // full unmount+remount of the provider subtree whenever entityId changes,
    // resetting selectedEntityId so stale A-entity state never leaks into B.
    // The provider's internal useEffect also resets on pathname change as a
    // belt-and-suspenders safeguard; key= is the primary fix.
    <SelectedEntityProvider key={entityId} anchorEntityId={entityId}>
      {/* GraphDepthProvider wraps both SelectedEntityProvider children so that
          GraphPanel (writes depth) and EntitySidebar (reads depth) share state.
          WHY nested inside SelectedEntityProvider: both contexts are needed by
          the same panels; nesting order doesn't matter since they're independent. */}
      <GraphDepthProvider>
      {/* ── Desktop layout (≥1280px) ─────────────────────────────────────── */}
      {/* WHY hidden xl:flex: below 1280px we render the mobile tab layout instead.
          xl = 1280px breakpoint in Tailwind. Three panels + a chat row below. */}
      <div
        className="hidden xl:flex flex-col h-full"
        // WHY flex flex-col h-full: the parent (<main>) is flex-1 overflow-y-auto
        // from (app)/layout.tsx. We fill its height and arrange children vertically
        // so the chat panel sticks to the bottom without needing position:sticky.
        aria-label="Intelligence page — desktop 3-column layout"
      >
        {/* ── 3-column resizable panel row ─────────────────────────────────── */}
        {/* WHY flex-1 overflow-hidden: this row takes all remaining height after
            the chat panel. overflow-hidden prevents the panel group from overflowing
            when Cytoscape renders at full height inside column 1. */}
        <div className="flex-1 overflow-hidden">
          <Group
            orientation="horizontal"
            // WHY id: required by react-resizable-panels for storage + accessibility
            // WHY orientation (not direction): react-resizable-panels v4 renamed
            // the prop from direction to orientation (breaking change from v3).
            id="intelligence-columns"
            className="h-full"
          >
            {/* ── Column 1: Graph panel (25%) ────────────────────────────── */}
            {/* WHY defaultSize={25}: starts at 25% of available width.
                minSize prevents the graph from being completely hidden by drag. */}
            <Panel
              id="col-graph"
              defaultSize={25}
              minSize={15}
              className="overflow-hidden"
            >
              {/* WHY h-full: the panel has no intrinsic height — it takes 100%
                  of the PanelGroup height so the Cytoscape graph fills the column. */}
              <div className="h-full overflow-hidden">
                {graphPanel}
              </div>
            </Panel>

            {/* ── Resize handle between col-1 and col-2 ─────────────────── */}
            {/* WHY hitAreaMargins: increases the draggable click target to 4px either
                side without changing the visual 1px line. Prevents frustrating misses. */}
            <Separator
              id="handle-1-2"
              className="w-[1px] bg-border hover:bg-primary/60 transition-colors cursor-col-resize"
              aria-label="Resize graph panel"
            />

            {/* ── Column 2: Intelligence panel (45%) ─────────────────────── */}
            <Panel
              id="col-intelligence"
              defaultSize={45}
              minSize={25}
              className="overflow-hidden"
            >
              <div className="h-full overflow-hidden">
                {intelligencePanel}
              </div>
            </Panel>

            {/* ── Resize handle between col-2 and col-3 ─────────────────── */}
            <Separator
              id="handle-2-3"
              className="w-[1px] bg-border hover:bg-primary/60 transition-colors cursor-col-resize"
              aria-label="Resize intelligence panel"
            />

            {/* ── Column 3: Sidebar (30%) ─────────────────────────────────── */}
            <Panel
              id="col-sidebar"
              defaultSize={30}
              minSize={20}
              className="overflow-hidden"
            >
              <div className="h-full overflow-hidden">
                {sidebarPanel}
              </div>
            </Panel>
          </Group>
        </div>

        {/* ── Full-width chat panel row ────────────────────────────────────── */}
        {/* WHY flex-none: the chat row has a fixed height (200px or 400px) —
            it should not participate in the flex distribution of the column row.
            EntityChatPanel manages its own expand/collapse height internally. */}
        <div className="flex-none border-t border-border">
          {chatPanel}
        </div>
      </div>

      {/* ── Mobile/small layout (<1280px) ────────────────────────────────── */}
      {/* WHY 4 tabs (Graph/Intelligence/Sidebar/Chat): each panel gets full
          viewport width on small screens. Using xl:hidden means this is only
          shown when the desktop layout is hidden. */}
      <div
        className="xl:hidden h-full flex flex-col"
        aria-label="Intelligence page — mobile tab layout"
      >
        <Tabs
          defaultValue="intelligence"
          className="flex flex-col h-full"
        >
          {/* WHY terminal variant: Bloomberg-style underline tabs match the
              rest of the app's panel tab design language. */}
          <TabsList
            variant="terminal"
            className="flex-none w-full justify-start px-2"
          >
            <TabsTrigger variant="terminal" value="graph">Graph</TabsTrigger>
            <TabsTrigger variant="terminal" value="intelligence">Intelligence</TabsTrigger>
            <TabsTrigger variant="terminal" value="sidebar">Summary</TabsTrigger>
            <TabsTrigger variant="terminal" value="chat">Chat</TabsTrigger>
          </TabsList>

          {/* WHY flex-1 overflow-auto on content: each panel fills the remaining
              height below the tab bar, with its own scroll container. */}
          <TabsContent value="graph" className="flex-1 overflow-auto mt-0">
            {graphPanel}
          </TabsContent>
          <TabsContent value="intelligence" className="flex-1 overflow-auto mt-0">
            {intelligencePanel}
          </TabsContent>
          <TabsContent value="sidebar" className="flex-1 overflow-auto mt-0">
            {sidebarPanel}
          </TabsContent>
          <TabsContent value="chat" className="flex-1 overflow-auto mt-0">
            {chatPanel}
          </TabsContent>
        </Tabs>
      </div>

      </GraphDepthProvider>
    </SelectedEntityProvider>
  );
}
