/**
 * components/ui/calendar.tsx — Calendar date-picker primitive
 *
 * WHY THIS EXISTS: react-day-picker v9 ships with no CSS — it requires either
 * importing their stylesheet or providing classNames for every element. We
 * provide classNames using Tailwind so the calendar inherits the Midnight Pro
 * dark theme automatically. This wrapper exists so:
 *   1. Consumers don't repeat 30+ classNames across the codebase.
 *   2. The Midnight Pro palette is applied once and enforced everywhere.
 *   3. v9 API changes (renamed props) are absorbed here, not in call sites.
 *
 * WHO USES IT: DateRangePicker, any form with a date field.
 *
 * DATA SOURCE: No S9 calls — pure presentation. Date values flow from the
 * parent form's RHF Controller.
 *
 * DESIGN REFERENCE: PLAN-0059 F-2 Form Layer — Finance terminal modal forms.
 *
 * v8 → v9 API NOTES (important for future maintainers):
 *   - `components.IconLeft/IconRight` renamed to `components.Chevron` with a
 *     `orientation` prop.
 *   - `classNames` keys now match UI enum values ("day_button" not "day").
 *   - `selected` type for range: `{ from: Date | undefined; to?: Date | undefined }`.
 *   - The `captionLayout` prop now accepts "label" | "dropdown" | "dropdown-years".
 */

"use client"; // WHY: DayPicker uses browser-side Date calculations and event handlers

import * as React from "react";
import { DayPicker } from "react-day-picker";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { cn } from "@/lib/utils";

export type CalendarProps = React.ComponentProps<typeof DayPicker>;

/**
 * Calendar — themed wrapper around react-day-picker v9 DayPicker.
 *
 * Applies Midnight Pro dark palette via classNames. Passes all props
 * through so mode="single" | "range" | "multiple" all work.
 */
export function Calendar({ className, classNames, showOutsideDays = true, ...props }: CalendarProps) {
  return (
    <DayPicker
      showOutsideDays={showOutsideDays}
      className={cn("p-3", className)}
      classNames={{
        // ── Layout ─────────────────────────────────────────────────────────
        months: "flex flex-col sm:flex-row gap-4",
        month: "space-y-4",
        month_caption: "flex justify-center pt-1 relative items-center",
        caption_label: "text-[12px] font-mono font-medium text-foreground",
        // ── Navigation ─────────────────────────────────────────────────────
        // WHY h-7 w-7: compact navigation matches the overall terminal density.
        nav: "flex items-center gap-1",
        button_previous: cn(
          "h-7 w-7 flex items-center justify-center rounded-[2px] border border-border/60",
          "bg-transparent text-muted-foreground hover:bg-muted/40 hover:text-foreground",
          "focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-primary",
          "absolute left-1",
        ),
        button_next: cn(
          "h-7 w-7 flex items-center justify-center rounded-[2px] border border-border/60",
          "bg-transparent text-muted-foreground hover:bg-muted/40 hover:text-foreground",
          "focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-primary",
          "absolute right-1",
        ),
        // ── Grid ───────────────────────────────────────────────────────────
        month_grid: "w-full border-collapse",
        weekdays: "flex",
        weekday: "text-[10px] font-mono text-muted-foreground w-9 text-center py-1",
        week: "flex w-full mt-1",
        // day is the cell; day_button is the clickable element inside it.
        day: "relative p-0 text-center",
        day_button: cn(
          "h-[36px] w-9 text-[11px] font-mono rounded-[2px] transition-colors",
          "hover:bg-muted/40 hover:text-foreground",
          "focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-primary",
        ),
        // ── Selection states ────────────────────────────────────────────────
        // WHY primary bg: the `--primary` CSS variable maps to #0EA5E9 (Midnight
        // Pro blue). Selected days use primary to match button/badge style.
        selected:
          "bg-primary text-primary-foreground hover:bg-primary hover:text-primary-foreground rounded-[2px]",
        // WHY range middle uses lower-opacity primary: the middle of a range is
        // "included" but not the "anchor" — lighter treatment guides the eye
        // toward the start and end handles.
        range_middle:
          "bg-primary/20 text-foreground rounded-none",
        range_start:
          "bg-primary text-primary-foreground rounded-l-[2px] rounded-r-none",
        range_end:
          "bg-primary text-primary-foreground rounded-r-[2px] rounded-l-none",
        // ── Special days ───────────────────────────────────────────────────
        today: "text-primary font-semibold",
        outside: "text-muted-foreground/40 aria-selected:bg-muted/20 aria-selected:text-muted-foreground",
        disabled: "text-muted-foreground/30 cursor-not-allowed hover:bg-transparent",
        hidden: "invisible",
        // Spread caller overrides last — they win over our defaults.
        ...classNames,
      }}
      components={{
        // WHY custom Chevron: react-day-picker v9 uses a single Chevron
        // component with an `orientation` prop for both arrows. We use
        // lucide-react icons to match the rest of the app's icon system.
        Chevron: ({ orientation }) =>
          orientation === "left" ? (
            <ChevronLeft className="h-4 w-4" />
          ) : (
            <ChevronRight className="h-4 w-4" />
          ),
      }}
      {...props}
    />
  );
}
Calendar.displayName = "Calendar";
