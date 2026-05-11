/**
 * components/ui/index.ts — Barrel export for shared UI components
 *
 * WHY THIS EXISTS: A single import surface (`@/components/ui`) keeps consumer
 * imports tidy and makes refactoring (rename / move) a one-file change.
 *
 * NOTE: Pre-existing shadcn primitives (button, card, etc.) keep their direct
 * paths so existing imports across the codebase do not need to change.
 * New PLAN-0059 F-2 primitives are exported here.
 */

export { MarkdownContent } from "./markdown-content";
export type { MarkdownContentProps } from "./markdown-content";

export { DashboardEmptyState } from "./dashboard-empty-state";
export type { DashboardEmptyStateProps } from "./dashboard-empty-state";

export { PeriodSelector } from "./period-selector";
export type { PeriodSelectorProps } from "./period-selector";

export { DataTimestamp } from "./data-timestamp";
export type { DataTimestampProps } from "./data-timestamp";

// ── PLAN-0059 F-2 — Form layer primitives ────────────────────────────────────
export {
  Form,
  FormControl,
  FormDescription,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
  useFormField,
} from "./form";

export { Calendar } from "./calendar";
export type { CalendarProps } from "./calendar";

export { DateRangePicker } from "./date-range-picker";
export type { DateRangePickerProps } from "./date-range-picker";

export { TimePicker } from "./time-picker";
export type { TimePickerProps } from "./time-picker";

export { QuickEditPopover } from "./quick-edit-popover";
export type { QuickEditPopoverProps } from "./quick-edit-popover";
