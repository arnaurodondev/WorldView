/**
 * components/ui/date-range-picker.tsx — Controlled date-range selector
 *
 * WHY THIS EXISTS: Finance users filter transactions, performance charts, and
 * news feeds by date ranges. The native `<input type="date">` has inconsistent
 * browser styling and no range semantics. This component provides:
 *   - A compact trigger button showing the formatted range.
 *   - A Popover calendar (react-day-picker range mode) that closes automatically
 *     when the end date is selected — matching Bloomberg's date-range UX.
 *   - Controlled value/onChange contract so it wires into RHF FormField
 *     without internal state surprises.
 *
 * WHO USES IT: Transaction history filters, performance range selectors,
 * any form field that requires a start+end date pair.
 *
 * DATA SOURCE: No S9 calls — pure UI. Date values flow to the parent form.
 *
 * DESIGN REFERENCE: PLAN-0059 F-2 Form Layer.
 */

"use client"; // WHY: uses useState for popover open state + browser Date API

import * as React from "react";
import { format } from "date-fns";
import { CalendarIcon } from "lucide-react";
import type { DateRange } from "react-day-picker";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Calendar } from "@/components/ui/calendar";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";

// ── Public API ────────────────────────────────────────────────────────────────

export interface DateRangePickerProps {
  /** The current date range. Undefined = no selection. */
  value: DateRange | undefined;
  /** Called whenever the user selects a date. The range may have `to: undefined`
   *  if only the start date has been picked. */
  onChange: (range: DateRange | undefined) => void;
  placeholder?: string;
  disabled?: boolean;
  /** "compact" matches terminal row height (h-7). "default" = h-9. "comfortable" = h-10. */
  density?: "compact" | "default" | "comfortable";
  /** Optional minimum selectable date (e.g. today for future-only ranges). */
  minDate?: Date;
  /** Optional maximum selectable date. */
  maxDate?: Date;
  className?: string;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

/**
 * formatRange — converts a DateRange to a compact display string.
 *
 * WHY two format strings:
 *   - Same year: "May 1 – May 15" (year omitted to save space in compact layouts)
 *   - Cross-year: "Dec 31, 2024 – Jan 5, 2025" (year included to prevent
 *     ambiguity — a finance user querying YTD vs TTM must see the year)
 */
function formatRange(range: DateRange | undefined, placeholder: string): string {
  if (!range?.from) return placeholder;

  const fromDate = range.from;
  const toDate = range.to;

  const sameYear = toDate ? fromDate.getFullYear() === toDate.getFullYear() : true;
  const dateFormat = sameYear ? "MMM d" : "MMM d, yyyy";

  const fromStr = format(fromDate, dateFormat);
  if (!toDate) return fromStr;
  return `${fromStr} – ${format(toDate, dateFormat)}`;
}

// ── Component ─────────────────────────────────────────────────────────────────

const DENSITY_HEIGHT: Record<NonNullable<DateRangePickerProps["density"]>, string> = {
  compact: "h-7 text-[11px]",
  default: "h-9 text-[12px]",
  comfortable: "h-10 text-[13px]",
};

export function DateRangePicker({
  value,
  onChange,
  placeholder = "Select date range",
  disabled,
  density = "compact",
  minDate,
  maxDate,
  className,
}: DateRangePickerProps) {
  const [open, setOpen] = React.useState(false);

  // Close the popover as soon as the user selects an end date — mirrors
  // Bloomberg's date-range UX where the picker dismisses on selection complete.
  const handleSelect = React.useCallback(
    (range: DateRange | undefined) => {
      onChange(range);
      // WHY check range.to: closing before `to` is set would prevent single-
      // click "from only" selections that the user then completes in a second
      // click. Only close when both endpoints are filled.
      if (range?.to) {
        setOpen(false);
      }
    },
    [onChange],
  );

  const label = formatRange(value, placeholder);
  const heightClass = DENSITY_HEIGHT[density];

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          variant="outline"
          disabled={disabled}
          className={cn(
            "w-full justify-start gap-2 font-mono tabular-nums",
            heightClass,
            // WHY muted when no value: visually distinguish placeholder from
            // a real date range so users know at a glance if a filter is set.
            !value?.from && "text-muted-foreground",
            className,
          )}
        >
          <CalendarIcon className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
          <span className="truncate">{label}</span>
        </Button>
      </PopoverTrigger>

      <PopoverContent
        // WHY w-auto: the calendar determines its own width (typically ~280px
        // for one month). Fixing the width at popover level clips the calendar.
        className="w-auto p-0"
        align="start"
      >
        <Calendar
          mode="range"
          selected={value}
          onSelect={handleSelect}
          // WHY defaultMonth: when a range is already set, open the calendar
          // at the from-date's month so the user sees context around their
          // existing selection.
          defaultMonth={value?.from}
          disabled={
            minDate || maxDate
              ? (day: Date) =>
                  (minDate ? day < minDate : false) ||
                  (maxDate ? day > maxDate : false)
              : undefined
          }
          numberOfMonths={1}
        />
      </PopoverContent>
    </Popover>
  );
}
