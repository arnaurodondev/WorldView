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
 *   WorkspaceTabs     — tab strip showing named workspaces
 *   WorkspaceGrid     — resizable panel grid (react-resizable-panels)
 *   WorkspacePanelContainer — per-panel chrome (header + close) + widget routing
 *
 * PLAN-0051 Wave C ADDITIONS (Part 2):
 *   - ShareWorkspaceDialog — encode active workspace into a shareable URL
 *   - NewFromTemplateDialog — create a workspace from one of 5 starter templates
 *   - Import path: when the URL has `?config=<token>`, decode it on mount and
 *     persist as a new workspace tab named "Imported".
 *
 * WHY config-import via localStorage write + reload (not direct context call):
 * WorkspaceContext.tsx is owned by Part 1 and may not yet expose an
 * addWorkspaceFromConfig method. To stay decoupled, we write directly to the
 * context's localStorage key with the imported workspace appended, then either:
 *   - reload the page (forces context to re-read from storage), OR
 *   - dispatch a `storage` event to nudge listeners.
 * We choose the reload path because it's the most reliable across React
 * lifecycles and the user is already in a "I just opened a shared link" mental
 * model where a one-time refresh is expected.
 *
 * WHO USES IT: Power users / institutional traders navigating via the sidebar.
 * DATA SOURCE: WorkspaceContext (localStorage), each panel widget calls S9 independently.
 * DESIGN REFERENCE: PRD-0031 §5 Workspace, PLAN-0051 §T-C-3-07
 */

"use client";
// WHY "use client": uses WorkspaceContext + SymbolLinkingContext hooks (client state),
// useEffect for the URL-import path, and react-resizable-panels (browser drag events).

import { useEffect, useRef } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import { SymbolLinkingProvider } from "@/contexts/SymbolLinkingContext";
import { WorkspaceTabs } from "@/components/workspace/WorkspaceTabs";
import { WorkspaceGrid } from "@/components/workspace/WorkspaceGrid";
import { ShareWorkspaceDialog } from "@/components/workspace/ShareWorkspaceDialog";
import { NewFromTemplateDialog } from "@/components/workspace/NewFromTemplateDialog";
import {
  useWorkspace,
  type WorkspaceConfig,
} from "@/contexts/WorkspaceContext";
import { decodeWorkspace } from "@/lib/workspace-share";
import type { WorkspaceTemplate } from "@/lib/workspace-templates";

// ── localStorage helpers (mirror WorkspaceContext keys) ────────────────────────

/**
 * WORKSPACES_STORAGE_KEY — must match the v2 key in WorkspaceContext.tsx.
 *
 * WHY duplicate the constant (not import): WorkspaceContext doesn't export the
 * key publicly, and importing it would couple this page to the internal storage
 * shape. Duplicating with a comment is safer — if Part 1 changes the key,
 * Part 2's import path here breaks visibly (unrenderable workspace) instead of
 * silently writing to the wrong key.
 */
const WORKSPACES_STORAGE_KEY = "worldview:workspaces:v2";
const ACTIVE_KEY = "worldview-active-workspace";

/**
 * appendWorkspaceAndReload — write a new workspace into localStorage and reload.
 *
 * WHY this approach (vs direct context mutation):
 *   - WorkspaceContext owns persistence; we don't want to fight its setState.
 *   - The page-mount import path is a one-shot operation per user session.
 *   - reload() guarantees the context re-reads localStorage from the freshest
 *     state — no race conditions with the context's own debounced saves.
 *
 * @param workspace — the WorkspaceConfig to append (minus id; we generate one)
 * @param namePrefix — optional human-friendly prefix for the assigned name
 *                    ("Imported", "Template: Day Trader", etc.)
 */
function appendWorkspaceAndReload(
  workspace: Omit<WorkspaceConfig, "id">,
  namePrefix = "Imported",
): void {
  if (typeof window === "undefined") return;

  // WHY try/catch: localStorage can throw on private browsing modes or quota
  // exhaustion. We don't want a failed import to crash the whole page.
  try {
    const raw = window.localStorage.getItem(WORKSPACES_STORAGE_KEY);
    const existing: WorkspaceConfig[] = raw ? (JSON.parse(raw) as WorkspaceConfig[]) : [];

    // WHY Date.now suffix on id: matches WorkspaceContext's addWorkspace pattern,
    // guaranteeing uniqueness across multiple rapid imports without a UUID lib.
    const ts = Date.now();
    const newWs: WorkspaceConfig = {
      ...workspace,
      id: `ws-imported-${ts}`,
      // WHY sanitize name: the imported name might be empty or absurdly long.
      // Trim to 24 chars and prefix to make the origin obvious in the tab strip.
      name: `${namePrefix}: ${(workspace.name || "Workspace").slice(0, 16)}`.slice(0, 24),
    };

    const updated = [...existing, newWs];
    window.localStorage.setItem(WORKSPACES_STORAGE_KEY, JSON.stringify(updated));
    window.localStorage.setItem(ACTIVE_KEY, newWs.id);

    // WHY full page reload (not a soft state nudge): the context loaded its
    // workspaces array via a useState lazy initializer that runs ONCE per
    // mount. There's no public API to ask the context to re-read storage.
    // A reload is the simplest, most reliable way to surface the new tab.
    window.location.reload();
  } catch (err) {
    // eslint-disable-next-line no-console
    console.error("Failed to append workspace to storage:", err);
  }
}

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
  const searchParams = useSearchParams();
  const router = useRouter();

  // WHY ref-guarded effect: useEffect runs in StrictMode twice during dev. We
  // must NOT import the same shared workspace twice. The ref ensures only the
  // first run does the import work.
  const importedRef = useRef(false);

  useEffect(() => {
    if (importedRef.current) return;
    const token = searchParams.get("config");
    if (!token) return;

    importedRef.current = true;
    const decoded = decodeWorkspace(token);
    if (!decoded) {
      // WHY console.warn (not toast): no toast system installed yet. Logging
      // gives debuggability while keeping the page functional. The user simply
      // sees the existing workspaces — no broken state from a corrupt token.
      // eslint-disable-next-line no-console
      console.warn("Invalid workspace share token; ignoring.");
      // Strip the bad query param so refreshing the page doesn't replay
      router.replace("/workspace");
      return;
    }

    // WHY strip id before append: the encoded workspace had a sender-side id
    // that we don't want to copy. appendWorkspaceAndReload generates a fresh id.
    const { id: _unused, ...rest } = decoded;
    void _unused;
    appendWorkspaceAndReload(rest, "Imported");
    // WHY no router.replace before reload: appendWorkspaceAndReload calls
    // window.location.reload() which discards the URL state anyway. A pre-
    // reload router.replace would just race with the reload.
  }, [searchParams, router]);

  /**
   * handleCreateFromTemplate — instantiate a chosen template as a new workspace.
   *
   * WHY also via appendWorkspaceAndReload: same persistence path as URL import.
   * Keeps both "create from URL" and "create from template" using one mechanism,
   * which is easier to reason about than two divergent paths.
   *
   * WHY the prefix is "Template": users seeing the new tab can immediately tell
   * its origin. Otherwise a freshly-created "Day Trader" workspace and a
   * shared "Day Trader" workspace would look identical.
   */
  function handleCreateFromTemplate(template: WorkspaceTemplate) {
    // WHY structuredClone (not just spread): WorkspaceConfig contains nested
    // arrays (rows → panels). A shallow spread would leave those arrays shared
    // with the template constant — subsequent edits would mutate the template,
    // breaking the next instantiation. structuredClone is deep + handles all
    // primitive types we use (string, number, arrays, objects).
    const cloned = structuredClone(template.config);
    appendWorkspaceAndReload(cloned, `Template`);
  }

  return (
    // WHY flex-col h-full: the workspace content area must fill the shell's main
    // content region (flex-1 in the layout). h-full ensures PanelGroup can calculate
    // viewport-relative heights for its resize calculations.
    <div className="flex flex-col h-full min-h-0">
      {/* ── Workspace tab strip + Wave C controls (Share + Template) ────── */}
      {/*
       * WHY a flex row wrapping WorkspaceTabs + Share + Template buttons:
       * Share/Template are workspace-LEVEL actions that pair naturally with
       * the tab strip. Sticking them at the right end of the same row keeps
       * all workspace-management affordances in one visual zone.
       *
       * WHY shrink-0 on the buttons but flex-1 on WorkspaceTabs: when the
       * tab strip overflows (many tabs), it scrolls horizontally inside its
       * own bounds without pushing the action buttons off-screen.
       */}
      {/*
       * WHY no border-b here (and no flex wrapper): WorkspaceTabs already
       * applies border-b border-border to its 32px tab strip. We render the
       * Share/Template buttons as a separate row beneath the tab strip to
       * avoid layout conflicts with WorkspaceTabs' internal flex/overflow
       * handling. The 24px utility row is just enough to comfortably hold
       * two text buttons without dominating the layout.
       */}
      <WorkspaceTabs />
      {activeWorkspace && (
        <div className="flex h-6 shrink-0 items-center justify-end gap-1 border-b border-border bg-background px-2">
          <NewFromTemplateDialog onCreate={handleCreateFromTemplate} />
          <ShareWorkspaceDialog config={activeWorkspace} />
        </div>
      )}

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
