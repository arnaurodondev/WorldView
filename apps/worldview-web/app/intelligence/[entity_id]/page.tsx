/**
 * app/intelligence/[entity_id]/page.tsx — Entity Intelligence page (PLAN-0074 Wave H)
 *
 * WHY THIS PAGE EXISTS:
 * The intelligence page provides a deep-dive analytical view of a single entity
 * (company, person, event, concept) built from the knowledge graph. It is distinct
 * from the instrument detail page (which shows market data) and the screener
 * (which compares instruments). This page focuses on:
 *   - The entity's relationship network (graph panel)
 *   - Evidence quality and confidence (intelligence tabs)
 *   - AI-generated narrative summaries (sidebar + history)
 *   - Entity-scoped AI chat (chat panel)
 *
 * ROUTE: /intelligence/[entity_id] where entity_id is a UUIDv7
 * This route lives at app/intelligence/[entity_id]/ (NOT under (app)/ route group)
 * because it needs a full-page layout without the collapsible sidebar overhead.
 *
 * WHY "use client":
 * The page assembles client-side components (all panels use TanStack Query hooks)
 * and reads the `useAuth()` hook for the access token. Server Components cannot
 * do this. The entity_id is read from params which works in both server and client
 * components, but the rest of the tree requires client-side.
 *
 * LAYOUT ARCHITECTURE:
 * The page renders <IntelligenceLayout> with four named slots:
 *   graphPanel       → <GraphPanel>          (Column 1)
 *   intelligencePanel→ <IntelligencePanel>   (Column 2)
 *   sidebarPanel     → <EntitySidebar>       (Column 3)
 *   chatPanel        → <EntityChatPanel>     (full-width bottom)
 *
 * SECURITY: API calls go through Next.js /api/* rewrite → S9 (R14).
 * Access token from React state only (never localStorage).
 */

"use client";
// WHY "use client": assembles client-side panels; useParams requires browser.

import { use } from "react";
import { IntelligenceLayout } from "@/components/intelligence/IntelligenceLayout";
import { GraphPanel } from "@/components/intelligence/GraphPanel";
import { IntelligencePanel } from "@/components/intelligence/IntelligencePanel";
import { EntitySidebar } from "@/components/intelligence/EntitySidebar";
import { EntityChatPanel } from "@/components/intelligence/EntityChatPanel";
import { IntelligencePageErrorBoundary } from "@/components/intelligence/IntelligencePageErrorBoundary";

// ── Types ─────────────────────────────────────────────────────────────────────

interface PageProps {
  params: Promise<{ entity_id: string }>;
}

// ── Page component ────────────────────────────────────────────────────────────

export default function IntelligencePage({ params }: PageProps) {
  // WHY use(params): Next.js 15 requires `use()` to unwrap async params.
  // This is the recommended App Router pattern for accessing route params
  // in client components. The `params` Promise resolves synchronously on
  // the client after hydration.
  const { entity_id: entityId } = use(params);

  return (
    // WHY h-screen overflow-hidden: the intelligence page takes the full
    // viewport height. Overflow is handled per-panel (each column scrolls
    // independently), not at the page level. This prevents double scrollbars.
    <div className="h-screen overflow-hidden bg-background">
      <IntelligenceLayout
        entityId={entityId}
        // WHY IntelligencePageErrorBoundary wrapping each panel:
        // Each panel fetches from a different S9 endpoint. If one fails
        // (e.g., the KG graph service is down), the other panels should
        // continue to function. Per-panel error boundaries ensure a single
        // panel failure never kills the entire intelligence page.
        graphPanel={
          <IntelligencePageErrorBoundary panelName="Graph">
            <GraphPanel entityId={entityId} />
          </IntelligencePageErrorBoundary>
        }
        intelligencePanel={
          <IntelligencePageErrorBoundary panelName="Intelligence">
            <IntelligencePanel entityId={entityId} />
          </IntelligencePageErrorBoundary>
        }
        sidebarPanel={
          <IntelligencePageErrorBoundary panelName="Sidebar">
            <EntitySidebar entityId={entityId} />
          </IntelligencePageErrorBoundary>
        }
        chatPanel={
          <IntelligencePageErrorBoundary panelName="Chat">
            <EntityChatPanel entityId={entityId} />
          </IntelligencePageErrorBoundary>
        }
      />
    </div>
  );
}
