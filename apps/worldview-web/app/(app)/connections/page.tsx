/**
 * app/(app)/connections/page.tsx — "Connections" discovery page (PLAN-0112 T-5-03)
 *
 * WHY A DEDICATED ROUTE (placement decision, documented per the task brief):
 * The two new PLAN-0112 surfaces are GRAPH-WIDE, not entity-scoped:
 *   1. WeirdConnectionsFeed — the global ranked "weird connections" feed.
 *   2. PathBetweenPanel    — pairwise "how are A and B related?".
 * Neither belongs under /intelligence/[entity_id] (which is single-entity scoped),
 * and bolting them onto an entity page would force the user to first pick an
 * unrelated anchor entity just to browse the global feed. The lowest-friction,
 * convention-consistent home is a top-level protected route under the (app) shell —
 * the same place /screener and /search live (both are global discovery surfaces).
 * A nav entry ("Connections", Spline icon) is added to CollapsibleSidebar.
 *
 * WHY TWO TABS (not two pages): the feed and the pairwise pathfinder are two views
 * of the SAME concept (weird KG connections). Tabs keep them one click apart and
 * mirror the existing IntelligencePanel tab idiom (Relations / Evidence / Paths …).
 *
 * ROUTE: /connections  (under app/(app)/ → inherits TopBar + sidebar shell + auth).
 * SECURITY: both child components fetch via /api/* → S9 (R14). Auth handled by the
 * (app) layout guard.
 */

"use client";
// WHY "use client": renders shadcn Tabs (Radix, browser) + the two client panels.

import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { WeirdConnectionsFeed } from "@/components/intelligence/WeirdConnectionsFeed";
import { PathBetweenPanel } from "@/components/intelligence/PathBetweenPanel";

export default function ConnectionsPage() {
  return (
    // WHY h-[calc(100vh-...)] style full-height column: the feed/pairwise bodies
    // scroll independently; the page itself does not add a second scrollbar.
    <div className="flex h-full flex-col overflow-hidden bg-background">
      {/* Page header */}
      <div className="border-b border-border/50 px-4 py-3">
        <h1 className="text-sm font-semibold text-foreground">Connections</h1>
        <p className="mt-0.5 text-[11px] text-muted-foreground">
          Surprising multi-hop links across the knowledge graph
        </p>
      </div>

      <Tabs defaultValue="feed" className="flex flex-1 flex-col overflow-hidden">
        <TabsList className="mx-4 mt-2 w-fit">
          <TabsTrigger value="feed">Weird Connections</TabsTrigger>
          <TabsTrigger value="pairwise">How are these related?</TabsTrigger>
        </TabsList>

        {/* WHY flex-1 overflow-hidden on each content: lets the inner panel own
            its scroll region so the tab strip stays pinned. */}
        <TabsContent value="feed" className="flex-1 overflow-hidden">
          <WeirdConnectionsFeed />
        </TabsContent>

        <TabsContent value="pairwise" className="flex-1 overflow-hidden">
          <PathBetweenPanel />
        </TabsContent>
      </Tabs>
    </div>
  );
}
