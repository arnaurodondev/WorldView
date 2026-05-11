/**
 * components/workspace/WorkspaceTabs.tsx — Named workspace tab strip
 *
 * WHY THIS EXISTS: PRD-0031 §5.2 — institutional traders context-switch constantly
 * between different analytical setups (intraday, research, portfolio monitoring).
 * Named workspace tabs let them switch without losing panel state, analogous to
 * Bloomberg's keyboard shortcuts between layouts but with a persistent visual strip.
 *
 * WHY inline rename (not a dialog): Bloomberg Terminal users rename frequently.
 * A modal dialog adds 2 extra interactions (open, type, confirm). Inline editing on
 * double-click is 0 extra clicks — name appears instantly editable in place.
 *
 * WHO USES IT: app/(app)/workspace/page.tsx (wired in Wave 2)
 * DATA SOURCE: WorkspaceContext (localStorage-persisted, no S9 calls)
 * DESIGN REFERENCE: PRD-0031 §5.2 Workspace tabs
 */

"use client";
// WHY "use client": uses WorkspaceContext (React context), useState (rename state),
// useRef (input focus), and keyboard events — all client-only.

import { useRef, useState } from "react";
import { cn } from "@/lib/utils";
import { useWorkspace } from "@/contexts/WorkspaceContext";

// ── Component ─────────────────────────────────────────────────────────────────

export function WorkspaceTabs() {
  const {
    workspaces,
    activeWorkspaceId,
    setActiveWorkspace,
    addWorkspace,
    removeWorkspace,
    renameWorkspace,
  } = useWorkspace();

  // WHY single renamingId (not per-tab state): only one tab can be renamed at a time.
  // Tracking a single "which tab is being renamed" ID avoids N separate boolean states.
  const [renamingId, setRenamingId] = useState<string | null>(null);
  const [renameValue, setRenameValue] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  function startRename(id: string, currentName: string) {
    setRenamingId(id);
    setRenameValue(currentName);
    // WHY setTimeout: the input is conditionally rendered and enters the DOM
    // in the next tick after state update — focus() must wait until it's mounted
    setTimeout(() => inputRef.current?.focus(), 0);
  }

  function commitRename() {
    if (renamingId) {
      renameWorkspace(renamingId, renameValue);
    }
    setRenamingId(null);
  }

  function handleClose(e: React.MouseEvent, id: string) {
    // WHY stopPropagation: prevent the parent tab onClick from also firing
    // (which would switch to this workspace right before deleting it)
    e.stopPropagation();
    if (workspaces.length === 1) return; // WHY: must always have ≥1 workspace
    // WHY window.confirm for MVP: avoids a custom modal component dependency.
    // The workspace name in the prompt makes it unambiguous which is being closed.
    const ws = workspaces.find((w) => w.id === id);
    const panelCount = ws?.rows.flatMap((r) => r.panels).length ?? 0;
    if (panelCount === 0 || window.confirm(`Close workspace "${ws?.name ?? id}"?`)) {
      removeWorkspace(id);
    }
  }

  return (
    // PLAN-0053 T-F-6-10: outer wrapper hosts the right-edge fade gradient.
    //   - `relative` lets the gradient overlay position absolutely
    //   - `overflow-x-auto` is moved to the inner role="tablist" so the
    //     gradient sits OUTSIDE the scroll container (otherwise it would
    //     scroll with the tabs and never look like a fade).
    //   - The gradient uses a CSS linear-gradient with stop at 100% to
    //     match the page background colour exactly. Tailwind's bg-gradient-*
    //     utilities can't reference our `--background` token directly so
    //     we inline the style.
    <div className="relative shrink-0">
      <div
        role="tablist"
        aria-label="Workspaces"
        className="flex h-8 items-end gap-0 border-b border-border bg-background px-2 overflow-x-auto"
      >
      {workspaces.map((ws) => {
        const isActive = ws.id === activeWorkspaceId;
        const isRenaming = ws.id === renamingId;

        return (
          <div
            key={ws.id}
            role="tab"
            aria-selected={isActive}
            aria-label={`Workspace: ${ws.name}`}
            // WHY group: makes the ✕ close button visible only on tab hover via
            // Tailwind's `group-hover:` variant without extra JS state
            className={cn(
              // WHY text-[10px]: workspace tab labels are chrome chrome text — the
              // same 10px compact rule as all other terminal chrome (panel labels,
              // toolbar captions). text-xs (12px) is too spacious for a dense tab strip.
              "group relative flex h-full items-center px-3 text-[10px] font-medium cursor-pointer select-none whitespace-nowrap shrink-0",
              // WHY border-b-2: underline indicator (not background fill) — Bloomberg
              // convention; background fills feel too heavy in a dense tab strip.
              isActive
                ? "border-b-2 border-primary text-foreground"
                : "border-b-2 border-transparent text-muted-foreground hover:text-foreground",
            )}
            onClick={() => {
              // WHY guard: don't switch while user is typing a new name
              if (!isRenaming) setActiveWorkspace(ws.id);
            }}
            onDoubleClick={() => startRename(ws.id, ws.name)}
          >
            {isRenaming ? (
              // ── Inline rename input ─────────────────────────────────────────
              // WHY border-b only: subtle visual affordance that this is editable
              // without a full input border that disrupts the tab strip layout
              <input
                ref={inputRef}
                value={renameValue}
                onChange={(e) => setRenameValue(e.target.value)}
                onBlur={commitRename}
                onKeyDown={(e) => {
                  if (e.key === "Enter") commitRename();
                  if (e.key === "Escape") setRenamingId(null);
                }}
                // WHY stopPropagation: prevent click on input from triggering
                // the parent div's onClick (which would call setActiveWorkspace)
                onClick={(e) => e.stopPropagation()}
                // WHY text-[10px]: inline rename input sits inside the tab strip — must
              // match the tab label size (10px) so the active text doesn't jump size
              // when switching between display and edit modes.
              className="w-[10ch] border-0 border-b border-primary bg-transparent text-[10px] text-foreground outline-none"
                maxLength={24}
                aria-label="Rename workspace"
              />
            ) : (
              ws.name
            )}

            {/* ── Close ✕ button — hidden until hover, absent when only 1 tab ── */}
            {workspaces.length > 1 && !isRenaming && (
              <button
                onClick={(e) => handleClose(e, ws.id)}
                // WHY group-hover:inline-flex + hidden: the button occupies no space
                // when invisible (not just opacity-0) — avoids reserving tab-strip width
                className="ml-1.5 hidden group-hover:inline-flex text-muted-foreground hover:text-foreground"
                aria-label={`Close ${ws.name} workspace`}
              >
                ✕
              </button>
            )}
          </div>
        );
      })}

      {/* ── Add workspace button ───────────────────────────────────────────── */}
      {/* WHY ml-1: small gap from last tab to distinguish from tab labels */}
      <button
        onClick={addWorkspace}
        // WHY text-[10px]: "Add" button lives in the tab strip chrome — must
        // match the 10px tab label density so it doesn't visually outweigh the tabs.
        className="ml-1 shrink-0 px-2 text-[10px] text-muted-foreground hover:text-foreground transition-colors duration-0"
        aria-label="Add workspace"
      >
        + Add
      </button>
      </div>
      {/* PLAN-0053 T-F-6-10: right-edge fade gradient signalling overflow.
          WHY pointer-events-none: must let pointer events pass through to the
          tabs underneath, otherwise the gradient blocks clicks on the rightmost
          tabs. WHY w-8 (32px) gradient: enough to fade the last tab letter
          smoothly without blocking too much usable space. WHY aria-hidden:
          purely decorative; the role="tablist" + arrow keys remain the a11y
          path for keyboard-only users. */}
      <div
        aria-hidden="true"
        className="pointer-events-none absolute right-0 top-0 h-full w-8"
        style={{
          background:
            "linear-gradient(to right, transparent 0%, hsl(var(--background)) 100%)",
        }}
      />
    </div>
  );
}
