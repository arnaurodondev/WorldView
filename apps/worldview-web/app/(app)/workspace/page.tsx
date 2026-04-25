/**
 * app/(app)/workspace/page.tsx — Named multi-panel Workspace page
 *
 * WHY THIS EXISTS: Institutional traders need simultaneous visibility into multiple
 * data streams. The Workspace (PRD-0031 §5) provides named, persistent layouts
 * with drag-to-resize panels — so a "Day Trading" configuration looks completely
 * different from a "Morning Brief" configuration, and both survive page refresh.
 *
 * ARCHITECTURE:
 *   WorkspaceContext  — named workspace configs, active workspace, add/remove/rename
 *   SymbolLinkingContext — per-workspace color-group symbol linking
 *   WorkspaceTabs     — tab strip showing named workspaces (from Wave 1)
 *   WorkspaceGrid     — resizable panel grid (react-resizable-panels)
 *   WorkspacePanelContainer — per-panel chrome (header + close) + widget routing
 *
 * WHY WorkspaceContext in layout.tsx AND this page uses SymbolLinkingContext here:
 *   WorkspaceContext is app-wide (layout needs it for the tab strip in the topbar).
 *   SymbolLinkingContext is workspace-scoped — it resets when switching workspaces,
 *   which is the correct behavior (Day Trading links are independent of Research links).
 *
 * WHO USES IT: Power users / institutional traders navigating via the sidebar.
 * DATA SOURCE: WorkspaceContext (localStorage), each panel widget calls S9 independently.
 * DESIGN REFERENCE: PRD-0031 §5 Workspace, canvas State A
 */

"use client";
// WHY "use client": uses WorkspaceContext + SymbolLinkingContext hooks (client state),
// and WorkspaceGrid uses react-resizable-panels which requires browser drag events.

import { SymbolLinkingProvider } from "@/contexts/SymbolLinkingContext";
import { WorkspaceTabs } from "@/components/workspace/WorkspaceTabs";
import { WorkspaceGrid } from "@/components/workspace/WorkspaceGrid";
import { useWorkspace } from "@/contexts/WorkspaceContext";

// ── Inner page — reads from WorkspaceContext (provided by layout.tsx) ──────────

/**
 * WorkspacePageInner — renders workspace tabs + grid for the active workspace.
 *
 * WHY separate inner component: WorkspaceProvider is already mounted in layout.tsx.
 * This component uses useWorkspace() directly rather than wrapping in another provider.
 * It's extracted from WorkspacePage to keep the exported page component clean.
 */
function WorkspacePageInner() {
  const { activeWorkspace } = useWorkspace();

  return (
    // WHY flex-col h-full: the workspace content area must fill the shell's main
    // content region (flex-1 in the layout). h-full ensures PanelGroup can calculate
    // viewport-relative heights for its resize calculations.
    <div className="flex flex-col h-full min-h-0">
      {/* ── Workspace tab strip ─────────────────────────────────────────── */}
      {/*
       * WHY WorkspaceTabs here (not in TopBar): tabs belong directly above the
       * workspace grid so the visual connection is immediate. Moving them to TopBar
       * would create distance between the tab selector and the panels it controls.
       */}
      <WorkspaceTabs />

      {/* ── Resizable panel grid ────────────────────────────────────────── */}
      {/*
       * WHY SymbolLinkingProvider wraps WorkspaceGrid: symbol linking is workspace-
       * scoped. When the active workspace changes (via tab click), WorkspaceTabs
       * updates WorkspaceContext.activeWorkspaceId, causing a re-render here.
       * Using the workspaceId as key resets SymbolLinkingProvider on workspace switch.
       */}
      {activeWorkspace ? (
        <SymbolLinkingProvider key={activeWorkspace.id}>
          <div className="flex-1 min-h-0">
            <WorkspaceGrid workspace={activeWorkspace} />
          </div>
        </SymbolLinkingProvider>
      ) : (
        // WHY inline empty state: §0.5 bans large centered empty states.
        // If no workspace is active (edge case), show a single line of text.
        <p className="px-2 py-1 text-[11px] text-muted-foreground">
          No workspace active. Add a workspace via the tab strip.
        </p>
      )}
    </div>
  );
}

// ── Exported page component ────────────────────────────────────────────────────

export default function WorkspacePage() {
  return <WorkspacePageInner />;
}
