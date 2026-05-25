/**
 * components/primitives/BulkActionToolbar.tsx — 22px row above tables
 *
 * WHY THIS EXISTS: PRD-0089 F1 §3.2 — when a user multi-selects rows in
 * Holdings / Tx Ledger / Screener / Workspace, we need a uniform action
 * strip immediately above the table. The strip appears only when ≥1 row
 * is selected and provides hotkey-discoverable actions. Bloomberg's
 * Watchlist Manager uses a near-identical strip with shortcut labels.
 * WHO USES IT: Holdings (sell, add lot), Tx Ledger (delete, edit),
 *   Screener (save, export), Workspace (group, ungroup).
 * DATA SOURCE: Pure presentational — caller manages selection state and
 *   action handlers.
 * DESIGN REFERENCE: PRD-0089 F1 §3.2 (BulkActionToolbar row).
 */

import type { ReactNode } from "react";

interface BulkAction {
  /** Action label rendered as text inside the button. */
  readonly label: string;
  /** Optional hotkey hint shown as a faint mono suffix (e.g. "⌘D"). */
  readonly hotkey?: string;
  /** Click handler. */
  readonly onAction: () => void;
  /** Optional destructive flag to color the button red. */
  readonly destructive?: boolean;
}

interface BulkActionToolbarProps {
  /** Number of currently selected rows. Toolbar hides when 0. */
  readonly selectedCount: number;
  /** Action buttons rendered left-to-right. */
  readonly actions: readonly BulkAction[];
  /** Clear-selection handler — bound to Esc by the parent table. */
  readonly onClear: () => void;
  /** Optional label suffix (e.g. "holdings", "rows"). */
  readonly entityLabel?: string;
}

export function BulkActionToolbar({
  selectedCount,
  actions,
  onClear,
  entityLabel = "rows",
}: BulkActionToolbarProps): ReactNode {
  // WHY hide at 0: bulk toolbar appearing on an empty selection is noise —
  // Bloomberg/Eikon show the strip only when relevant. Parent tables don't
  // need to gate-render; this component handles its own visibility.
  if (selectedCount < 1) return null;

  return (
    <div
      role="toolbar"
      aria-label="Bulk actions"
      className="flex h-[22px] items-center justify-between border-b border-border-strong bg-muted/40 px-1.5 text-[11px]"
    >
      <div className="flex items-center gap-2">
        <span className="font-mono tabular-nums text-foreground">
          {selectedCount} {entityLabel} selected
        </span>
        <button
          type="button"
          onClick={onClear}
          className="text-[10px] uppercase tracking-wide text-muted-foreground transition-color-only duration-100 hover:text-foreground"
        >
          Clear
        </button>
      </div>
      <div className="flex items-center gap-2">
        {actions.map((a) => (
          <button
            key={a.label}
            type="button"
            onClick={a.onAction}
            className={`flex items-center gap-1 text-[11px] transition-color-only duration-100 ${
              a.destructive
                ? "text-destructive hover:text-destructive/80"
                : "text-foreground hover:text-primary"
            }`}
          >
            <span>{a.label}</span>
            {a.hotkey ? (
              <span className="font-mono text-[10px] text-muted-foreground">{a.hotkey}</span>
            ) : null}
          </button>
        ))}
      </div>
    </div>
  );
}
