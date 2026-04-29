/**
 * components/screener/ColumnSettingsPopover.tsx — ⚙ icon → column visibility & order
 *
 * WHY THIS EXISTS (PLAN-0051 T-B-2-06): every analyst wants different columns.
 * A long-only investor wants P/E + Dividend Yield. A momentum trader wants
 * Volume + Chg%. Persisting per-user column preferences (visibility + order)
 * is table-stakes for any institutional screener.
 *
 * WHY a Popover (not a side-panel or full Dialog):
 *   - The list of columns is tiny (≤15). A popover anchored to the gear
 *     icon is fast to open, fast to dismiss, and stays visually adjacent
 *     to the table being modified.
 *   - Side panel would force a layout shift; Dialog would be too heavyweight.
 *
 * WHY HTML5 native drag/drop (not react-dnd, not @dnd-kit):
 *   - The plan explicitly says "no new lib". We have ~15 list rows, no
 *     virtualisation, no nested drop-zones — vanilla draggable + dragstart/
 *     dragover/drop is sufficient and ships zero KB.
 *   - HTML5 DnD has known quirks (no touch on iOS Safari, ghost-image awkward)
 *     but the desktop terminal use case is the priority audience.
 *
 * WHY checkboxes (not switches):
 *   - "Show this column" is an attribute, not an action. Checkboxes encode
 *     binary attributes; switches encode actions/states (per Material Design
 *     guidelines). Picking the right control prevents user surprise.
 *
 * WHY Reset clears localStorage AND in-memory state:
 *   - One click should fully revert. If we only cleared in-memory, the next
 *     reload would resurrect stale prefs. If we only cleared localStorage,
 *     the popover would still show the user's last edits until reload.
 *
 * WHO USES IT: app/(app)/screener/page.tsx (gear button next to filter bar)
 */

"use client";
// WHY "use client": uses useState for local edit buffer, dispatches drag
// events, and reads/writes localStorage via the columns helpers.

import { useState } from "react";
import { Settings2, GripVertical, RotateCcw } from "lucide-react";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import {
  type ScreenerColumn,
  saveColumnPrefs,
  resetColumnPrefs,
} from "@/lib/screener-columns";
import { cn } from "@/lib/utils";

// ── Props ────────────────────────────────────────────────────────────────────

export interface ColumnSettingsPopoverProps {
  /** Current ordered + visibility-flagged column list (page state). */
  columns: ScreenerColumn[];
  /** Called whenever the user changes columns; parent persists + re-renders table. */
  onChange: (next: ScreenerColumn[]) => void;
}

// ── Component ────────────────────────────────────────────────────────────────

export function ColumnSettingsPopover({ columns, onChange }: ColumnSettingsPopoverProps) {
  // WHY a local "dragging index" state: HTML5 DnD APIs are stateful in the
  // DOM but React doesn't know about it. Tracking the source index lets us
  // compute the splice on drop without touching dataTransfer.
  const [dragIdx, setDragIdx] = useState<number | null>(null);

  function handleToggle(idx: number) {
    const next = columns.map((c, i) => (i === idx ? { ...c, visible: !c.visible } : c));
    onChange(next);
    saveColumnPrefs(next);
  }

  function handleDragStart(idx: number, e: React.DragEvent<HTMLLIElement>) {
    setDragIdx(idx);
    // WHY effectAllowed move: hints to the browser this is a re-order, not a copy.
    // Some browsers won't fire dragover without a setData() call — set a no-op string.
    e.dataTransfer.effectAllowed = "move";
    e.dataTransfer.setData("text/plain", String(idx));
  }

  function handleDragOver(e: React.DragEvent<HTMLLIElement>) {
    // WHY preventDefault on dragover: the default behaviour rejects the drop;
    // we must block the default for the drop event to fire afterwards.
    e.preventDefault();
    e.dataTransfer.dropEffect = "move";
  }

  function handleDrop(targetIdx: number) {
    if (dragIdx === null || dragIdx === targetIdx) {
      setDragIdx(null);
      return;
    }
    const next = [...columns];
    const [moved] = next.splice(dragIdx, 1);
    next.splice(targetIdx, 0, moved);
    setDragIdx(null);
    onChange(next);
    saveColumnPrefs(next);
  }

  function handleReset() {
    const fresh = resetColumnPrefs();
    onChange(fresh);
  }

  return (
    <Popover>
      <PopoverTrigger asChild>
        <button
          type="button"
          aria-label="Configure columns"
          className="flex h-7 w-7 items-center justify-center rounded-[2px] text-muted-foreground hover:text-foreground hover:bg-white/[0.04] transition-colors"
          title="Show / hide / reorder columns"
        >
          <Settings2 className="h-3.5 w-3.5" aria-hidden />
        </button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-64 p-2">
        <div className="flex items-center justify-between mb-1 px-1">
          <span className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground font-mono">
            Columns
          </span>
          <button
            type="button"
            onClick={handleReset}
            className="flex items-center gap-1 text-[10px] uppercase tracking-[0.06em] font-mono text-muted-foreground hover:text-foreground"
            aria-label="Reset columns to default"
          >
            <RotateCcw className="h-3 w-3" aria-hidden />
            Reset
          </button>
        </div>
        <ul role="list" aria-label="Column visibility and order">
          {columns.map((col, idx) => (
            <li
              key={col.key}
              draggable
              onDragStart={(e) => handleDragStart(idx, e)}
              onDragOver={handleDragOver}
              onDrop={() => handleDrop(idx)}
              className={cn(
                "flex items-center gap-1 px-1 py-1 rounded-[2px] cursor-move text-[11px]",
                "hover:bg-white/[0.04]",
                dragIdx === idx && "opacity-50",
              )}
            >
              <GripVertical className="h-3 w-3 text-muted-foreground shrink-0" aria-hidden />
              {/* WHY <label> wrapping checkbox + text: bigger click target */}
              <label className="flex flex-1 items-center gap-2 cursor-pointer min-w-0">
                <input
                  type="checkbox"
                  checked={col.visible}
                  onChange={() => handleToggle(idx)}
                  className="h-3 w-3 accent-primary shrink-0"
                  aria-label={`Toggle ${col.label} column visibility`}
                />
                <span className="truncate text-foreground">{col.label}</span>
              </label>
            </li>
          ))}
        </ul>
      </PopoverContent>
    </Popover>
  );
}
