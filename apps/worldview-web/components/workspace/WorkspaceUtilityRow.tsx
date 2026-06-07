/**
 * components/workspace/WorkspaceUtilityRow.tsx — 24px utility strip above the panel grid
 *
 * WHY THIS EXISTS: The workspace page needs workspace-level actions (Add panel, Template,
 * Share) and the CrosshairSync toggle in one 24px strip, matching the density spec from
 * PRD-0089 DESIGN-09 §A.4 ("Utility row — 24px").
 *
 * WHY a separate component (not inline in page.tsx):
 * - PRD-0089 §A.5 component table specifies this as WorkspaceUtilityRow.tsx.
 * - Testable in isolation — the Vitest test can render just this strip.
 * - The CrosshairSyncToggle reads from WorkspaceSyncContext; extracting the strip
 *   keeps workspace/page.tsx clean of sync-context imports.
 *
 * CROSSHAIR SYNC DESIGN:
 * The toggle writes to WorkspaceSyncContext.setSyncEnabled. OHLCVChart panels
 * that are subscribed to the context will react to syncEnabled going true/false
 * and register/unregister their crosshair move listeners accordingly.
 *
 * WHY CrosshairSyncToggle is inline (not a separate file): at ~20 lines it is
 * below the threshold for a standalone file. PRD-0089 §A.5 explicitly says
 * "CrosshairSyncToggle — NEW in WorkspaceUtilityRow.tsx | ~20".
 *
 * WHO USES IT: app/(app)/workspace/page.tsx, rendered between WorkspaceTabs and WorkspaceGrid.
 * DESIGN REFERENCE: PRD-0089 DESIGN-09 §A.4 utility row, §A.5 component table.
 */

"use client";
// WHY "use client": reads WorkspaceSyncContext (hook), renders interactive buttons.

import { useWorkspaceSync } from "@/contexts/WorkspaceSyncContext";
import type { WorkspaceConfig } from "@/contexts/WorkspaceContext";

// ── CrosshairSyncToggle ────────────────────────────────────────────────────────

/**
 * CrosshairSyncToggle — a button that enables/disables crosshair sync across
 * all chart panels in the workspace.
 *
 * WHY this exact UI (not a checkbox/switch): Bloomberg-style toggles are
 * terminal-weight buttons that show their state via a glyph change (⊕/⊗)
 * rather than a toggle switch — switches feel too consumer-product for the
 * institutional density target.
 *
 * WHY ⊕ for ON and ⊗ for OFF: ⊕ (circled-plus) reads as "connected/linked",
 * ⊗ (circled-times) reads as "disconnected/cancelled". Standard TradingView
 * crosshair sync iconography maps to this convention.
 */
function CrosshairSyncToggle() {
  const { syncEnabled, setSyncEnabled } = useWorkspaceSync();

  return (
    <button
      type="button"
      data-testid="crosshair-sync-toggle"
      onClick={() => setSyncEnabled(!syncEnabled)}
      // WHY aria-pressed: this is a stateful toggle — screen readers need to
      // announce "pressed" / "not pressed" when the state changes.
      aria-pressed={syncEnabled}
      aria-label={syncEnabled ? "Disable crosshair sync" : "Enable crosshair sync"}
      className={[
        // Base terminal button style: no rounded corners, monospace, 10px.
        "flex items-center gap-1 rounded-[2px] px-2 py-0.5",
        "font-mono text-[10px] uppercase tracking-[0.06em]",
        "transition-colors duration-0",
        // WHY border instead of bg: toggled-off state should be subtle (border only);
        // toggled-on gets a yellow primary tint to signal "active mode".
        syncEnabled
          ? "border border-primary/60 bg-primary/10 text-primary"
          : "border border-border/40 bg-muted/20 text-muted-foreground hover:text-foreground hover:bg-muted/40",
      ].join(" ")}
    >
      {/* Glyph changes with state — gives visual confirmation without relying on color alone. */}
      <span aria-hidden>{syncEnabled ? "⊕" : "⊗"}</span>
      <span>{syncEnabled ? "Sync on" : "Sync off"}</span>
    </button>
  );
}

// ── WorkspaceUtilityRow ────────────────────────────────────────────────────────

export interface WorkspaceUtilityRowProps {
  /** Active workspace config — needed so onShare can encode it. */
  workspace: WorkspaceConfig;
  /** Called when the user clicks "Add panel +" */
  onAddPanel: () => void;
  /** Called when the user clicks "Template ⊞" */
  onTemplate: () => void;
  /** Called when the user clicks "Share ↗" */
  onShare: () => void;
}

export function WorkspaceUtilityRow({
  workspace: _workspace,
  onAddPanel,
  onTemplate,
  onShare,
}: WorkspaceUtilityRowProps) {
  return (
    // WHY h-6 (24px): exactly the height spec from §A.4 ("Utility row — 24px").
    // WHY shrink-0: the grid below this row is flex-1 and must get all remaining space.
    // WHY border-b border-border: structural hairline divider separating utility chrome
    // from the panel grid. No shadow — matches Bloomberg's 1-pixel divider convention.
    <div
      data-testid="workspace-utility-row"
      className="flex h-6 shrink-0 items-center justify-end gap-1 border-b border-border bg-background px-2"
    >
      {/* ── Left cluster: Add panel, Template, Share ─────────────────────── */}
      {/*
       * WHY right-aligned on the whole strip (justify-end on parent):
       * The spec §A.4 places the button cluster on the RIGHT side of the
       * utility row ("Right-aligned cluster"). The workspace grid area to
       * the left of these controls is intentionally empty — the tab strip
       * already occupies the full width above it.
       */}

      {/* Add panel — opens the add-panel tray */}
      <button
        type="button"
        data-testid="add-panel-button"
        onClick={onAddPanel}
        aria-label="Add a new panel to the workspace"
        className="flex items-center gap-1 rounded-[2px] border border-border/40 bg-muted/20 px-2 py-0.5
                   font-mono text-[10px] uppercase tracking-[0.06em] text-muted-foreground
                   hover:bg-muted/40 hover:text-foreground transition-colors duration-0"
      >
        {/* WHY inline + after label (not before): Bloomberg-style — the action word
            comes first, the icon follows. Prevents the symbol from being clipped
            at small widths while the label remains legible. */}
        Add panel <span aria-hidden>＋</span>
      </button>

      {/* Template — opens NewFromTemplateDialog */}
      <button
        type="button"
        data-testid="template-button"
        onClick={onTemplate}
        aria-label="Create workspace from a template"
        className="flex items-center gap-1 rounded-[2px] border border-border/40 bg-muted/20 px-2 py-0.5
                   font-mono text-[10px] uppercase tracking-[0.06em] text-muted-foreground
                   hover:bg-muted/40 hover:text-foreground transition-colors duration-0"
      >
        Template <span aria-hidden>⊞</span>
      </button>

      {/* Share — opens ShareWorkspaceDialog */}
      <button
        type="button"
        data-testid="share-button"
        onClick={onShare}
        aria-label="Share this workspace via a URL"
        className="flex items-center gap-1 rounded-[2px] border border-border/40 bg-muted/20 px-2 py-0.5
                   font-mono text-[10px] uppercase tracking-[0.06em] text-muted-foreground
                   hover:bg-muted/40 hover:text-foreground transition-colors duration-0"
      >
        Share <span aria-hidden>↗</span>
      </button>

      {/* ── Separator ────────────────────────────────────────────────────── */}
      {/*
       * WHY a 1px separator between action buttons and the toggle:
       * The CrosshairSync toggle is a persistent workspace-level setting,
       * not a one-off action. Visual separation communicates this distinction
       * at a glance — the left cluster is "verbs", the right button is "a mode".
       */}
      <span className="mx-1 h-3 w-px bg-border/60" aria-hidden />

      {/* ── CrosshairSyncToggle ───────────────────────────────────────────── */}
      {/*
       * WHY toggle on the far right: it is the most persistent control here —
       * users set it once and leave it. Rightmost position gives it a stable
       * "corner anchor" feel matching Bloomberg's top-right panel chrome cluster.
       */}
      <CrosshairSyncToggle />
    </div>
  );
}
