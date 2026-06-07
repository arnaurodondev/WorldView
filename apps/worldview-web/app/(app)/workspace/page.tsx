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

import { useEffect, useRef, useState } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import { SymbolLinkingProvider } from "@/contexts/SymbolLinkingContext";
import { WorkspaceSymbolProvider, useWorkspaceSymbol } from "@/contexts/WorkspaceSymbolContext";
// WHY WorkspaceSyncProvider here (not in layout.tsx): crosshair sync is workspace-scoped
// state. It should reset when the user navigates away from /workspace and should
// be separate from global app context.
import { WorkspaceSyncProvider } from "@/contexts/WorkspaceSyncContext";
import { WorkspaceTabs } from "@/components/workspace/WorkspaceTabs";
// PLAN-0059 G-2: WorkspaceGrid stays statically imported. Considered for
// dynamic-import (it pulls react-resizable-panels + every panel widget) but
// /workspace is already a separate Next route bundle — splitting the grid
// inside it doesn't save initial bundle on other routes, and existing tests
// expect synchronous panel render. The widget-level lazy-loading happens
// via the per-panel components (FundamentalsTab uses next/dynamic for
// EntityGraphPanel, etc.), which is the meaningful split point here.
import { WorkspaceGrid } from "@/components/workspace/WorkspaceGrid";
import { ShareWorkspaceDialog } from "@/components/workspace/ShareWorkspaceDialog";
import { NewFromTemplateDialog } from "@/components/workspace/NewFromTemplateDialog";
// PRD-0089 Wave J: new 24px utility strip with Add panel / Template / Share / CrosshairSync.
import { WorkspaceUtilityRow } from "@/components/workspace/WorkspaceUtilityRow";
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
 * appendWorkspaceToStorage — write a new workspace into localStorage and notify.
 *
 * PLAN-0053 T-F-6-11: previously this function called window.location.reload()
 * because WorkspaceContext only read storage on mount. We now dispatch a
 * synthetic 'storage' event after writing — WorkspaceContext (since the same
 * task) listens for it and re-reads state without a hard reload. Together
 * with router.replace('/workspace') this gives a clean import path that
 * preserves the React tree and TanStack Query cache.
 *
 * WHY this approach (vs direct context mutation):
 *   - WorkspaceContext owns persistence; we don't want to fight its setState.
 *   - The page-mount import path is a one-shot operation per user session.
 *   - The storage-event handshake mirrors the cross-tab refresh path, so we
 *     get "open in another tab" parity for free.
 *
 * @param workspace — the WorkspaceConfig to append (minus id; we generate one)
 * @param namePrefix — optional human-friendly prefix for the assigned name
 *                    ("Imported", "Template: Day Trader", etc.)
 * @returns true on success, false on storage error.
 */
function appendWorkspaceToStorage(
  workspace: Omit<WorkspaceConfig, "id">,
  namePrefix = "Imported",
): boolean {
  if (typeof window === "undefined") return false;

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

    // PLAN-0053 T-F-6-11: synthetic 'storage' event — WorkspaceContext
    // listens for this and re-reads from localStorage. WHY new StorageEvent
    // (not a CustomEvent): native storage events flow through addEventListener
    // ('storage', ...) for free; using the native shape keeps the listener
    // simple and gives cross-tab parity. Modern browsers all support the
    // StorageEvent constructor (Chrome 6+, Safari 5+, Firefox 3.6+).
    window.dispatchEvent(
      new StorageEvent("storage", {
        key: WORKSPACES_STORAGE_KEY,
        newValue: JSON.stringify(updated),
      }),
    );
    return true;
  } catch (err) {
    // eslint-disable-next-line no-console
    console.error("Failed to append workspace to storage:", err);
    return false;
  }
}

// ── WorkspaceSymbolBar ─────────────────────────────────────────────────────────

/**
 * WorkspaceSymbolBar — Bloomberg-style workspace-level symbol input.
 *
 * WHY THIS EXISTS: Bloomberg Terminal has a "Security" input at the top of each
 * workspace. Typing a symbol there simultaneously updates ALL panels — chart,
 * fundamentals, news — to show the entered ticker. This component replicates that
 * UX, broadcast via WorkspaceSymbolContext.
 *
 * WHY a local inputValue state (separate from broadcastSymbol):
 * We only broadcast when the user presses Enter or clears with Escape. While the
 * user is typing (inputValue changes), panels should NOT switch symbols on every
 * keystroke — that would cause a torrent of API calls for partial inputs like
 * "A", "AA", "AAP", "AAPL". Separate local state lets us commit on Enter only.
 *
 * WHY uppercase on onChange: financial tickers are always uppercase. Real-time
 * uppercasing prevents the jarring "I have to hold Shift" friction.
 *
 * WHY Escape to clear: matching Bloomberg's keyboard behaviour — Escape is the
 * universal "cancel" key in terminal UIs, and clearing the broadcast symbol
 * restores per-panel colour-group linking.
 *
 * WHO USES IT: WorkspacePageInner (rendered above the tab strip + grid)
 */
function WorkspaceSymbolBar() {
  const { broadcastSymbol, setBroadcastSymbol } = useWorkspaceSymbol();

  // WHY local inputValue: see file-level comment above. We hold the transient
  // typed value here and only commit it to the context on Enter.
  const [inputValue, setInputValue] = useState(broadcastSymbol ?? "");

  return (
    // WHY border-b border-border/40: subtle divider between this bar and the
    // tab strip below. Half opacity so it doesn't compete with the tab strip's
    // own bottom border.
    <div className="flex items-center gap-2 border-b border-border/40 bg-card/30 px-3 py-1.5">
      {/* WHY "Symbol" label in uppercase muted text: mirrors Bloomberg's "Security:"
          label style — compact, terminal-weight, non-intrusive. */}
      <span className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
        Symbol
      </span>

      {/* ── Symbol input ───────────────────────────────────────────────── */}
      {/*
       * WHY w-24 (96px): wide enough for a 5-char ticker (e.g., "GOOGL") plus
       * a 3-char exchange suffix (e.g., ".US") without overflow. Narrow enough
       * to stay unobtrusive beside the label.
       *
       * WHY rounded-[2px]: matches the terminal-quality 2px border-radius used
       * on all buttons and inputs in the workspace (DESIGN_SYSTEM.md §2.1).
       *
       * WHY font-mono uppercase: tickers are displayed in monospace uppercase
       * throughout the terminal. This input matches that convention so the text
       * style doesn't shift when the value is committed.
       */}
      <input
        data-testid="workspace-symbol-input"
        value={inputValue}
        onChange={(e) => setInputValue(e.target.value.toUpperCase())}
        onKeyDown={(e) => {
          if (e.key === "Enter") {
            // WHY trim: guards against "AAPL " (trailing space from auto-complete)
            setBroadcastSymbol(inputValue.trim() || null);
          }
          if (e.key === "Escape") {
            // WHY clear both: Escape resets both the local input AND the broadcast
            // symbol so panels revert to their per-panel linked symbols.
            setBroadcastSymbol(null);
            setInputValue("");
          }
        }}
        placeholder="e.g. AAPL"
        className="h-6 w-24 rounded-[2px] border border-border/40 bg-transparent px-2 font-mono text-[11px] uppercase text-foreground placeholder:text-muted-foreground/40 focus:border-primary/50 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
        aria-label="Broadcast symbol to all panels"
      />

      {/* ── Clear button — only shown when a symbol is broadcast ───────── */}
      {/*
       * WHY conditional render (not always visible): an always-visible clear
       * button would waste space when nothing is broadcast. Showing it only
       * when broadcastSymbol is set matches the Bloomberg "clear the security"
       * affordance which appears only when a security is active.
       */}
      {broadcastSymbol && (
        <button
          onClick={() => {
            setBroadcastSymbol(null);
            setInputValue("");
          }}
          aria-label="Clear broadcast symbol"
          className="text-[10px] text-muted-foreground hover:text-foreground"
        >
          ×
        </button>
      )}

      {/* ── Usage hint ─────────────────────────────────────────────────── */}
      {/*
       * WHY dimmed hint text (not tooltip): the bar is always visible — a
       * tooltip requires hover. The hint is tiny (10px, 40% opacity) so it
       * reads as ambient help, not primary content.
       */}
      <span className="text-[10px] text-muted-foreground/40">
        Press Enter to push symbol to all panels
      </span>
    </div>
  );
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

  // WHY booleans for dialog open state here (not in WorkspaceUtilityRow):
  // The NewFromTemplateDialog and ShareWorkspaceDialog are already instantiated
  // below with state wired to the page-level state. The WorkspaceUtilityRow
  // just calls the callbacks — it doesn't own the dialog state.
  const [_templateOpen, _setTemplateOpen] = useState(false);
  const [_shareOpen, _setShareOpen] = useState(false);

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
    // that we don't want to copy. appendWorkspaceToStorage generates a fresh id.
    const { id: _unused, ...rest } = decoded;
    void _unused;
    const ok = appendWorkspaceToStorage(rest, "Imported");
    // PLAN-0053 T-F-6-11: replace the URL with /workspace so the ?config=
    // token is gone (so refresh / share won't re-import) AND the React tree
    // stays mounted (no full-page reload). The storage event dispatched
    // inside appendWorkspaceToStorage already nudged the context to refresh.
    if (ok) router.replace("/workspace");
  }, [searchParams, router]);

  /**
   * handleCreateFromTemplate — instantiate a chosen template as a new workspace.
   *
   * WHY also via appendWorkspaceToStorage: same persistence path as URL import.
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
    // PLAN-0053 T-F-6-11: same import path as URL config — write storage,
    // dispatch a synthetic 'storage' event so WorkspaceContext refreshes.
    appendWorkspaceToStorage(cloned, `Template`);
  }

  return (
    // WHY flex-col h-full: the workspace content area must fill the shell's main
    // content region (flex-1 in the layout). h-full ensures PanelGroup can calculate
    // viewport-relative heights for its resize calculations.
    //
    // WHY WorkspaceSymbolProvider here (not in layout.tsx): broadcast symbol is
    // workspace-session-local. Placing the provider at this level means the symbol
    // state resets when the user navigates away from /workspace — correct behaviour.
    // Each workspace tab switch does NOT reset it (they're all inside this one
    // WorkspacePageInner instance); only navigating away from /workspace resets.
    // WHY WorkspaceSyncProvider wraps WorkspaceSymbolProvider: crosshair sync must
    // be available to all chart panels inside the grid, which are nested inside both
    // providers. The sync provider is workspace-scoped (resets on /workspace leave).
    <WorkspaceSyncProvider>
    <WorkspaceSymbolProvider>
      <div className="flex flex-col h-full min-h-0">
        {/* ── Bloomberg-style workspace symbol bar ─────────────────────── */}
        {/*
         * WHY above WorkspaceTabs: the symbol bar is a workspace-level control
         * that persists across tab switches (same broadcastSymbol applies to all
         * workspace tabs until explicitly cleared). Rendering it above the tab
         * strip makes this hierarchy visually obvious — it's a workspace property,
         * not a per-tab property.
         */}
        <WorkspaceSymbolBar />

        {/* ── Workspace tab strip + Wave C controls (Share + Template) ── */}
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
          // PRD-0089 Wave J: replaced the old inline button row with WorkspaceUtilityRow.
          // The dialogs (NewFromTemplateDialog / ShareWorkspaceDialog) use custom trigger
          // elements so their open state stays inside the dialog components.
          // WorkspaceUtilityRow's onTemplate/onShare callbacks programmatically open them
          // via the hidden trigger refs below.
          <>
            {/* Hidden trigger refs — allow WorkspaceUtilityRow buttons to open dialogs */}
            {/*
             * WHY hidden span with dialog inside: WorkspaceUtilityRow fires onTemplate /
             * onShare callbacks. We need those callbacks to open the respective dialogs.
             * The dialogs own their open state internally (not controlled from outside).
             * Solution: render the dialogs with custom trigger elements that are hidden
             * (sr-only), and expose a ref-accessible button. Then the utility row callback
             * simulates a click on that hidden button.
             *
             * SIMPLER ALTERNATIVE: pass open/setOpen to dialogs. But the dialog components
             * only expose `trigger` prop (not `open`). Modifying them is out of scope.
             * The hidden-trigger pattern is a common workaround for uncontrolled Radix dialogs.
             */}
            <span className="sr-only">
              <NewFromTemplateDialog
                onCreate={handleCreateFromTemplate}
                trigger={
                  <button
                    id="workspace-template-trigger"
                    aria-label="Open template dialog"
                    type="button"
                  />
                }
              />
              <ShareWorkspaceDialog
                config={activeWorkspace}
                trigger={
                  <button
                    id="workspace-share-trigger"
                    aria-label="Open share dialog"
                    type="button"
                  />
                }
              />
            </span>
            <WorkspaceUtilityRow
              workspace={activeWorkspace}
              onAddPanel={() => {
                // WHY dispatch custom event: WorkspaceGrid owns the tray open state
                // internally. We can signal it to open via a custom DOM event rather
                // than prop-drilling a setter through the page → grid chain.
                // This keeps the coupling loose — the grid listens, the page fires.
                window.dispatchEvent(new CustomEvent("workspace:open-add-panel-tray"));
              }}
              onTemplate={() => {
                // Simulate click on the hidden trigger button that opens the dialog
                const btn = document.getElementById("workspace-template-trigger");
                btn?.click();
              }}
              onShare={() => {
                const btn = document.getElementById("workspace-share-trigger");
                btn?.click();
              }}
            />
          </>
        )}

        {/* ── Resizable panel grid ──────────────────────────────────────── */}
        {/*
         * WHY SymbolLinkingProvider wraps WorkspaceGrid: symbol linking is workspace-
         * scoped. When the active workspace changes (via tab click), WorkspaceTabs
         * updates WorkspaceContext.activeWorkspaceId, causing a re-render here.
         * Using the workspaceId as key resets SymbolLinkingProvider on workspace switch.
         *
         * WHY SymbolLinkingProvider is INSIDE WorkspaceSymbolProvider: the broadcast
         * symbol context must be available to WorkspaceChartWidget. Both providers
         * are workspace-scoped; the ordering (outer=Symbol, inner=Linking) is arbitrary.
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
    </WorkspaceSymbolProvider>
    </WorkspaceSyncProvider>
  );
}

// ── Exported page component ────────────────────────────────────────────────────

export default function WorkspacePage() {
  return <WorkspacePageInner />;
}
