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
    // WHY h-8 (32px): sub-bar below TopBar (36px chrome) — distinct but subordinate.
    // WHY border-b: separates the tab row from workspace content below it.
    // WHY overflow-x-auto: when many workspaces are open, the strip scrolls horizontally
    // rather than wrapping or truncating tab labels.
    <div
      role="tablist"
      aria-label="Workspaces"
      className="flex h-8 items-end gap-0 border-b border-border bg-background px-2 overflow-x-auto shrink-0"
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
              "group relative flex h-full items-center px-3 text-xs font-medium cursor-pointer select-none whitespace-nowrap shrink-0",
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
                className="w-[10ch] border-0 border-b border-primary bg-transparent text-xs text-foreground outline-none"
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
        className="ml-1 shrink-0 px-2 text-xs text-muted-foreground hover:text-foreground transition-colors duration-0"
        aria-label="Add workspace"
      >
        + Add
      </button>
    </div>
  );
}
