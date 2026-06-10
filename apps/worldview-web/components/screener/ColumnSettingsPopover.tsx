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

import { useEffect, useState } from "react";
import { Settings2, GripVertical, RotateCcw, Check } from "lucide-react";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
// Round 2: native <input type=checkbox> replaced with the shadcn/ui Checkbox
// (Radix). WHY: design-system consistency (every other checkbox surface —
// Technical section, settings pages — uses the Radix primitive with the
// shared disabled-contrast tokens), and the disabled state for essential
// columns needs the AA-compliant disabled styling baked into ui/checkbox.tsx.
import { Checkbox } from "@/components/ui/checkbox";
import {
  type ScreenerColumn,
  ESSENTIAL_COLUMN_KEYS,
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
  /**
   * PLAN-0053 T-F-6-07: when true, the sparkline column is currently
   * suppressed because the loaded result set exceeds the 200-row threshold.
   * The popover renders an inline explainer so the user understands why
   * their visible-checked sparkline column isn't drawing in the table.
   */
  sparklineSuppressed?: boolean;
}

// ── Component ────────────────────────────────────────────────────────────────

export function ColumnSettingsPopover({
  columns,
  onChange,
  sparklineSuppressed = false,
}: ColumnSettingsPopoverProps) {
  // WHY a local "dragging index" state: HTML5 DnD APIs are stateful in the
  // DOM but React doesn't know about it. Tracking the source index lets us
  // compute the splice on drop without touching dataTransfer.
  const [dragIdx, setDragIdx] = useState<number | null>(null);

  // PLAN-0053 T-F-6-06: "Saved" inline-tick state. Flipped to true on each
  // change; auto-cleared after 1.5s so the indicator doesn't permanently
  // stick around. WHY a state flag (not always-on): "your prefs are auto-
  // saved" is implicit — flashing the tick gives positive confirmation
  // without cluttering the popover when nothing has changed recently.
  const [savedTick, setSavedTick] = useState(false);
  useEffect(() => {
    if (!savedTick) return;
    const handle = window.setTimeout(() => setSavedTick(false), 1500);
    return () => window.clearTimeout(handle);
  }, [savedTick]);

  function handleToggle(idx: number) {
    // Essential columns (ticker, name) are non-hideable — the checkbox is
    // rendered disabled, but we ALSO guard here because Radix can still fire
    // onCheckedChange through keyboard activation paths in some versions, and
    // a state-level guard is the invariant we actually care about.
    if (ESSENTIAL_COLUMN_KEYS.includes(columns[idx]?.key)) return;
    const next = columns.map((c, i) => (i === idx ? { ...c, visible: !c.visible } : c));
    onChange(next);
    saveColumnPrefs(next);
    setSavedTick(true);
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
    setSavedTick(true);
  }

  function handleReset() {
    const fresh = resetColumnPrefs();
    onChange(fresh);
    setSavedTick(true);
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
          <Settings2 className="h-3.5 w-3.5" aria-hidden strokeWidth={1.5} />
        </button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-64 p-2">
        <div className="flex items-center justify-between mb-1 px-1">
          <span className="flex items-center gap-1.5 text-[10px] uppercase tracking-[0.08em] text-muted-foreground font-mono">
            Columns
            {/* PLAN-0053 T-F-6-06: inline ✓ Saved. WHY aria-live=polite: the
                tick is short-lived, but a screen reader user benefits from a
                spoken "Saved" cue when their preference is persisted. */}
            {savedTick && (
              <span
                className="flex items-center gap-0.5 text-[10px] uppercase tracking-[0.06em] text-positive"
                aria-live="polite"
              >
                <Check className="h-3 w-3" aria-hidden strokeWidth={1.5} />
                Saved
              </span>
            )}
          </span>
          <button
            type="button"
            onClick={handleReset}
            className="flex items-center gap-1 text-[10px] uppercase tracking-[0.06em] font-mono text-muted-foreground hover:text-foreground"
            aria-label="Reset columns to default"
          >
            <RotateCcw className="h-3 w-3" aria-hidden strokeWidth={1.5} />
            Reset
          </button>
        </div>
        {/* PLAN-0053 T-F-6-07: sparkline auto-disable explainer.
            WHY at top (above the list): users notice the explanation as they
            open the popover. Mounting it next to the specific sparkline row
            would require row-targeted styling and a dynamic position lookup. */}
        {sparklineSuppressed && (
          <p
            role="note"
            className="mb-1 rounded-[2px] border border-warning/40 bg-warning/5 px-1.5 py-1 text-[10px] leading-snug text-warning/90"
          >
            Sparklines hidden for &gt;200 rows. Apply more filters or load fewer to
            re-enable.
          </p>
        )}
        <ul role="list" aria-label="Column visibility and order">
          {columns.map((col, idx) => {
            // Essential columns (ticker, name) are pinned-on: checkbox renders
            // checked + disabled so users SEE the column exists in the list
            // (omitting the row entirely would read as a bug) but can't hide it.
            const essential = ESSENTIAL_COLUMN_KEYS.includes(col.key);
            return (
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
                <GripVertical className="h-3 w-3 text-muted-foreground shrink-0" aria-hidden strokeWidth={1.5} />
                {/* WHY <label htmlFor>: Radix Checkbox renders a <button>
                    (a labelable element), so clicking the text still toggles —
                    preserving the big-click-target behaviour of the previous
                    <label>-wrapped native input. */}
                <Checkbox
                  id={`col-toggle-${col.key}`}
                  checked={col.visible}
                  disabled={essential}
                  onCheckedChange={() => handleToggle(idx)}
                  // WHY h-3 w-3 override: the shared Checkbox defaults to 16px;
                  // this popover is a dense 11px-text list — 12px boxes match
                  // the previous native-input footprint so the layout is stable.
                  className="h-3 w-3 shrink-0 [&_svg]:h-2.5 [&_svg]:w-2.5"
                  aria-label={`Toggle ${col.label} column visibility`}
                />
                <label
                  htmlFor={`col-toggle-${col.key}`}
                  className={cn(
                    "flex flex-1 items-center gap-2 min-w-0",
                    essential ? "cursor-default" : "cursor-pointer",
                  )}
                >
                  <span className="truncate text-foreground">{col.label}</span>
                  {/* "pinned" tag explains WHY the checkbox is disabled —
                      a disabled control with no explanation reads as broken. */}
                  {essential && (
                    <span className="ml-auto text-[9px] font-mono uppercase tracking-[0.06em] text-muted-foreground/60">
                      pinned
                    </span>
                  )}
                </label>
              </li>
            );
          })}
        </ul>
      </PopoverContent>
    </Popover>
  );
}
