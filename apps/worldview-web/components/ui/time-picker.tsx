/**
 * components/ui/time-picker.tsx — HH:MM time input with optional timezone selector
 *
 * WHY THIS EXISTS: Finance users schedule alerts, set market-session filters,
 * and configure notification times. The native `<input type="time">` has no
 * timezone awareness and inconsistent browser chrome. This component:
 *   1. Provides two separate HH / MM inputs for explicit time entry.
 *   2. Clamps values on blur (HH 00–23, MM 00–59) so the user can type
 *      freely and get auto-corrected — same UX as Bloomberg's time entry.
 *   3. Optionally shows a timezone selector from the curated market-centre
 *      list so the user knows what timezone the time is expressed in.
 *
 * WHO USES IT: Alert rule creation, scheduled-export configuration, any form
 * with a time field.
 *
 * DATA SOURCE: No S9 calls — pure UI.
 *
 * DESIGN REFERENCE: PLAN-0059 F-2 Form Layer.
 */

"use client"; // WHY: uses useState for internal HH/MM display state + onBlur events

import * as React from "react";
import { cn } from "@/lib/utils";
import { inputVariants, type InputDensity } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { CURATED_FALLBACK } from "@/lib/timezones";

// ── Types ──────────────────────────────────────────────────────────────────

export interface TimePickerProps {
  /** Current time as "HH:MM" (24-hour). Undefined = no value. */
  value: string | undefined;
  /** Called with the new "HH:MM" string on every change. */
  onChange: (value: string) => void;
  /** When provided, renders a timezone selector (IANA string). */
  timezone?: string;
  /** Called when the user changes the timezone. */
  onTimezoneChange?: (tz: string) => void;
  disabled?: boolean;
  density?: InputDensity;
}

// ── Helpers ────────────────────────────────────────────────────────────────

/** Parse a "HH:MM" string into separate hour and minute integers.
 *  Returns { hh: 0, mm: 0 } if the value is missing or malformed. */
function parseTime(value: string | undefined): { hh: number; mm: number } {
  if (!value) return { hh: 0, mm: 0 };
  const [rawH = "0", rawM = "0"] = value.split(":");
  const hh = Math.max(0, Math.min(23, parseInt(rawH, 10) || 0));
  const mm = Math.max(0, Math.min(59, parseInt(rawM, 10) || 0));
  return { hh, mm };
}

/** Zero-pad a number to exactly 2 digits: 0 → "00", 9 → "09", 23 → "23". */
function pad2(n: number): string {
  return String(n).padStart(2, "0");
}

// ── Component ──────────────────────────────────────────────────────────────

export function TimePicker({
  value,
  onChange,
  timezone,
  onTimezoneChange,
  disabled,
  density = "compact",
}: TimePickerProps) {
  const { hh, mm } = parseTime(value);

  // Local display strings — can be partially typed (e.g. "2" before "23").
  // WHY split HH/MM display from the committed "HH:MM" value: if we kept a
  // single string, typing "2" in the hour field would immediately format to
  // "02" and move focus, which is jarring. Committing only on blur gives the
  // user freedom to type naturally.
  const [displayHH, setDisplayHH] = React.useState<string>(() => pad2(hh));
  const [displayMM, setDisplayMM] = React.useState<string>(() => pad2(mm));

  // Sync display state when the parent resets the value externally.
  React.useEffect(() => {
    const { hh: newHH, mm: newMM } = parseTime(value);
    setDisplayHH(pad2(newHH));
    setDisplayMM(pad2(newMM));
  }, [value]);

  /**
   * commitHH — clamp and persist the hour field on blur or Enter.
   *
   * WHY clamp to 00–23: 24-hour time has no "24". If the user types "25" or
   * "99", we snap to 23 rather than rejecting the input and showing an error
   * (an error on a time field would be disproportionate UX for a simple typo).
   */
  const commitHH = React.useCallback(
    (raw: string) => {
      const parsed = parseInt(raw, 10);
      const clamped = isNaN(parsed) ? 0 : Math.max(0, Math.min(23, parsed));
      setDisplayHH(pad2(clamped));
      const { mm: currentMM } = parseTime(value);
      onChange(`${pad2(clamped)}:${pad2(currentMM)}`);
    },
    [value, onChange],
  );

  /**
   * commitMM — clamp and persist the minute field on blur or Enter.
   *
   * WHY clamp to 00–59: same rationale as commitHH above.
   */
  const commitMM = React.useCallback(
    (raw: string) => {
      const parsed = parseInt(raw, 10);
      const clamped = isNaN(parsed) ? 0 : Math.max(0, Math.min(59, parsed));
      setDisplayMM(pad2(clamped));
      const { hh: currentHH } = parseTime(value);
      onChange(`${pad2(currentHH)}:${pad2(clamped)}`);
    },
    [value, onChange],
  );

  const baseInputClass = cn(
    inputVariants({ density }),
    "w-10 text-center tabular-nums font-mono p-0",
  );

  return (
    <div className="flex items-center gap-1.5">
      {/* HH input */}
      <input
        type="text"
        inputMode="numeric"
        maxLength={2}
        disabled={disabled}
        value={displayHH}
        aria-label="Hours"
        placeholder="HH"
        onChange={(e) => setDisplayHH(e.target.value)}
        onBlur={(e) => commitHH(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter") commitHH(e.currentTarget.value);
        }}
        className={baseInputClass}
      />

      {/* Colon separator — purely visual, not interactive */}
      <span
        aria-hidden
        className="text-[13px] font-mono text-muted-foreground select-none"
      >
        :
      </span>

      {/* MM input */}
      <input
        type="text"
        inputMode="numeric"
        maxLength={2}
        disabled={disabled}
        value={displayMM}
        aria-label="Minutes"
        placeholder="MM"
        onChange={(e) => setDisplayMM(e.target.value)}
        onBlur={(e) => commitMM(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter") commitMM(e.currentTarget.value);
        }}
        className={baseInputClass}
      />

      {/* Timezone selector — only rendered when the `timezone` prop is provided.
          WHY optional: not every time field has timezone context. Alert rules use
          the user's account timezone (from PreferencesContext) and don't need an
          inline selector. Explicit scheduling forms (future trade-ticket) do. */}
      {timezone !== undefined && onTimezoneChange && (
        <Select value={timezone} onValueChange={onTimezoneChange} disabled={disabled}>
          <SelectTrigger
            className={cn(
              "w-48 font-mono",
              density === "compact" ? "h-7 text-[11px]" : "h-9 text-[12px]",
            )}
          >
            <SelectValue placeholder="Timezone" />
          </SelectTrigger>
          <SelectContent>
            {CURATED_FALLBACK.map((tz) => (
              <SelectItem
                key={tz.value}
                value={tz.value}
                className="text-[11px] font-mono"
              >
                {tz.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      )}
    </div>
  );
}
