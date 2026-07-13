/**
 * components/portfolio/HoldingsColumnGroupToggle.tsx — ⚙ Core/Portfolio/Advanced
 * column-group toggle for the holdings table (PLAN-0122 W-E, PRD-0122 §6.7).
 *
 * WHY THIS EXISTS: the holdings table has 15 data columns. §6.7 lets the user
 * show/hide them a GROUP at a time (Core / Portfolio / Advanced) instead of
 * column-by-column, so a casual power user can dial detail up or down with one
 * click. Core is always on (it anchors the row — ticker + actions + the six
 * essentials) so its checkbox is checked + disabled.
 *
 * WHY A POPOVER (DS §6.5d, mirrors screener/ColumnSettingsPopover): three
 * checkboxes anchored to a gear icon is fast to open/dismiss and stays visually
 * adjacent to the table. A side panel would force a layout shift; a Dialog is too
 * heavyweight for three toggles.
 *
 * WHY IT SELF-GATES ON `mode` (returns null in Simple): §6.7/R-26 hides the toggle
 * in Simple mode — Simple always shows exactly the Core group, so exposing a
 * group toggle there would be a control that does nothing. Gating INSIDE the
 * component (not only at the call site) keeps the contract in one place and makes
 * the "hidden in Simple" behaviour unit-testable in isolation.
 *
 * PERSISTENCE: toggling a group calls `saveGroupState()` (→
 * `worldview:holdingsColGroups:v1`) AND `onChange(next)` so the parent updates the
 * table's `columnGroups` prop, which re-applies visibility. Core is normalised on
 * before every write so the stored blob can never claim Core is off.
 *
 * WHO USES IT: HoldingsTab (mounted in the HoldingsTableChrome row, Advanced only).
 */

"use client";
// WHY "use client": renders a Radix Popover + Checkbox (stateful UI) and writes
// localStorage via saveGroupState.

import { Settings2, RotateCcw } from "lucide-react";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { Checkbox } from "@/components/ui/checkbox";
import {
  type HoldingsColGroups,
  ADVANCED_GROUP_DEFAULT,
  saveGroupState,
} from "@/lib/portfolio/holdings-column-groups";

// ── Props ────────────────────────────────────────────────────────────────────
export interface HoldingsColumnGroupToggleProps {
  /** Current enabled-groups state (owned by HoldingsTab). */
  groups: HoldingsColGroups;
  /** Called with the next state whenever the user toggles/resets a group. */
  onChange: (next: HoldingsColGroups) => void;
  /**
   * Render mode. In "simple" the toggle is not rendered at all (§6.7/R-26).
   * Default "advanced" so a bare mount (tests) shows the control.
   */
  mode?: "simple" | "advanced";
}

// The two user-toggleable groups (Core is locked-on). Declared as data so the
// checkbox list stays in sync with the copy strings (§6.7).
const TOGGLEABLE: ReadonlyArray<{
  key: "portfolio" | "advanced";
  label: string;
}> = [
  { key: "portfolio", label: "Portfolio detail" },
  { key: "advanced", label: "Advanced metrics" },
];

// ── Component ────────────────────────────────────────────────────────────────
export function HoldingsColumnGroupToggle({
  groups,
  onChange,
  mode = "advanced",
}: HoldingsColumnGroupToggleProps) {
  // R-26: the group toggle is Advanced-only. Simple forces Core-only and hides
  // this control entirely.
  if (mode === "simple") return null;

  // apply — persist + propagate. Core is always coerced on (saveGroupState also
  // normalises it) so the anchors can never be toggled off.
  function apply(next: HoldingsColGroups) {
    const normalised: HoldingsColGroups = { ...next, core: true };
    saveGroupState(normalised);
    onChange(normalised);
  }

  function handleToggle(key: "portfolio" | "advanced", checked: boolean) {
    apply({ ...groups, [key]: checked });
  }

  function handleReset() {
    // Reset restores the Advanced default = all groups on (every column except
    // divYld, which keeps its own hide) — "today's layout".
    apply({ ...ADVANCED_GROUP_DEFAULT });
  }

  return (
    <Popover>
      <PopoverTrigger asChild>
        <button
          type="button"
          aria-label="Show or hide table columns"
          title="Show / hide column groups"
          // data-tour-target consumed by the W-F onboarding tour (step 5).
          data-tour-target="column-toggle"
          // Same footprint + focus-ring as the screener gear (DS §6.5d).
          className="flex h-7 w-7 items-center justify-center rounded-[2px] text-muted-foreground hover:text-foreground hover:bg-white/[0.04] transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
        >
          <Settings2 className="h-3.5 w-3.5" aria-hidden strokeWidth={1.5} />
        </button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-56 p-2">
        <div className="mb-1 flex items-center justify-between px-1">
          <span className="font-mono text-[10px] uppercase tracking-[0.08em] text-muted-foreground">
            Columns
          </span>
          <button
            type="button"
            onClick={handleReset}
            aria-label="Reset columns to default"
            className="flex items-center gap-1 rounded-[2px] font-mono text-[10px] uppercase tracking-[0.06em] text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
          >
            <RotateCcw className="h-3 w-3" aria-hidden strokeWidth={1.5} />
            Reset to default
          </button>
        </div>
        <ul role="list" aria-label="Column groups">
          {/* Core — always on, checkbox checked + disabled (it anchors the row).
              A visible-but-locked row explains WHY it can't be hidden (a missing
              row would read as a bug). */}
          <li className="flex items-center gap-2 rounded-[2px] px-1 py-1 text-[11px]">
            <Checkbox
              id="colgroup-core"
              checked
              disabled
              className="h-3 w-3 shrink-0 [&_svg]:h-2.5 [&_svg]:w-2.5"
              aria-label="Core columns (always shown)"
            />
            <label
              htmlFor="colgroup-core"
              className="flex flex-1 cursor-default items-center gap-2"
            >
              <span className="text-foreground">Core (always shown)</span>
              <span className="ml-auto font-mono text-[9px] uppercase tracking-[0.06em] text-muted-foreground/60">
                locked
              </span>
            </label>
          </li>

          {TOGGLEABLE.map(({ key, label }) => (
            <li
              key={key}
              className="flex items-center gap-2 rounded-[2px] px-1 py-1 text-[11px] hover:bg-white/[0.04]"
            >
              <Checkbox
                id={`colgroup-${key}`}
                checked={groups[key]}
                onCheckedChange={(v) => handleToggle(key, v === true)}
                className="h-3 w-3 shrink-0 [&_svg]:h-2.5 [&_svg]:w-2.5"
                aria-label={`Toggle ${label} columns`}
              />
              <label
                htmlFor={`colgroup-${key}`}
                className="flex flex-1 cursor-pointer items-center gap-2"
              >
                <span className="text-foreground">{label}</span>
              </label>
            </li>
          ))}
        </ul>
      </PopoverContent>
    </Popover>
  );
}
