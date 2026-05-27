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

import { Fragment, useEffect, useState } from "react";
import { Settings2, GripVertical, RotateCcw, Check } from "lucide-react";
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
// PRD-0089 Wave I-A · T-IA-08: backend-pending marker for columns whose
// underlying field isn't in the screener fields allowlist yet.
import { BackendPendingBadge } from "@/components/ui/backend-pending-badge";

// ── T-IA-08 category map ─────────────────────────────────────────────────────
// WHY a static category map (not derived from `field_type`): the screener
// columns metadata lives in `lib/screener-columns.ts` which doesn't expose a
// category field today. Hardcoding the map here is pragmatic; if/when the
// metadata table grows a `category` column we'll switch to it in a follow-up.
// Any column key NOT present here falls into the "Other" bucket so we
// silently surface new opt-in columns instead of dropping them.
type ColCategory = "Valuation" | "Profitability" | "Technical" | "Intelligence" | "Other";

const COLUMN_CATEGORY: Record<string, ColCategory> = {
  ticker: "Other",
  name: "Other",
  sector: "Other",
  price: "Other",
  change: "Technical",
  marketCap: "Valuation",
  pe: "Valuation",
  forwardPe: "Valuation",
  revenueGrowth: "Profitability",
  divYield: "Valuation",
  roe: "Profitability",
  beta: "Technical",
  score: "Intelligence",
  range52w: "Technical",
  sparkline: "Technical",
  opMargin: "Profitability",
  evEbitda: "Valuation",
  avgVol: "Technical",
};

// WHY a set (not an array of strings): O(1) "is this backend pending?"
// lookup inside the render loop. Today the set is empty — every opt-in
// column we ship is already backed by a live field. Wave L-2..L-5 columns
// will be added to this set as they ship behind a Wave-L track gate.
const BACKEND_PENDING_KEYS: ReadonlySet<string> = new Set<string>();

// WHY 14 (not 12 or 16): the 1440 px viewport (the platform's design target)
// fits ~14 dense screener columns before the AG-Grid horizontal scroll bar
// surfaces. Past that, columns clip — see plan §6.3 density re-check.
const MAX_VISIBLE_COLUMNS = 14;

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
            // T-IA-08 grouping: render a category header ABOVE the first
            // row of each category. WHY this approach (instead of N <ul>s):
            // keeping ONE <ul> preserves the HTML5 drag-drop ordering across
            // categories — users can drag "Score" from Intelligence into
            // Technical and the splice index math still works.
            const category = COLUMN_CATEGORY[col.key] ?? "Other";
            const prevCategory = idx > 0
              ? (COLUMN_CATEGORY[columns[idx - 1]!.key] ?? "Other")
              : null;
            const showHeader = prevCategory !== category;
            const isPending = BACKEND_PENDING_KEYS.has(col.key);

            return (
              // WHY Fragment with key: React requires keys on list children;
              // we render TWO elements per iteration (optional header + row).
              <Fragment key={col.key}>
                {showHeader && (
                  // WHY a non-draggable <li> (not <h4>): keeps the row inside
                  // the same <ul> so screen readers walk the headers and
                  // the column rows in document order.
                  <li
                    role="presentation"
                    className="px-1 pt-1.5 pb-0.5 text-[9px] uppercase tracking-[0.08em] font-mono text-muted-foreground/70 select-none cursor-default"
                  >
                    {category}
                  </li>
                )}
                <li
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
                  {/* T-IA-08: badge for columns whose backend field isn't
                   *  in the allowlist yet. Today the set is empty; Wave L
                   *  tracks will add keys. */}
                  {isPending && <BackendPendingBadge text="L-pending" />}
                </li>
              </Fragment>
            );
          })}
        </ul>
        {/* T-IA-08 footer warning. WHY two states (muted vs warning): the
         *  same line stays in place so the user always sees the rule; only
         *  the colour escalates once the threshold is breached. */}
        <p
          role="note"
          className={cn(
            "mt-1 px-1 pb-0.5 text-[9px] font-mono leading-snug",
            columns.filter((c) => c.visible).length > MAX_VISIBLE_COLUMNS
              ? "text-warning"
              : "text-muted-foreground",
          )}
        >
          More than {MAX_VISIBLE_COLUMNS} columns will horizontally scroll past
          the 1440 px viewport.
        </p>
      </PopoverContent>
    </Popover>
  );
}
