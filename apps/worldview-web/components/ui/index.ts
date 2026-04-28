/**
 * components/ui/index.ts — Barrel export for shared UI components
 *
 * WHY THIS EXISTS: PLAN-0049 Wave B introduces several cross-feature shared
 * components. A single import surface (`@/components/ui`) keeps consumer
 * imports tidy and makes refactoring (rename / move) a one-file change.
 *
 * NOTE: only PLAN-0049 additions are re-exported here. Pre-existing shadcn
 * primitives (button, card, etc.) keep their direct paths so existing imports
 * across the codebase do not need to change.
 */

export { MarkdownContent } from "./markdown-content";
export type { MarkdownContentProps } from "./markdown-content";

export { DashboardEmptyState } from "./dashboard-empty-state";
export type { DashboardEmptyStateProps } from "./dashboard-empty-state";

export { PeriodSelector } from "./period-selector";
export type { PeriodSelectorProps } from "./period-selector";

export { DataTimestamp } from "./data-timestamp";
export type { DataTimestampProps } from "./data-timestamp";
