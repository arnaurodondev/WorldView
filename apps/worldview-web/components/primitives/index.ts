/**
 * components/primitives/index.ts — barrel re-exports
 *
 * WHY THIS EXISTS: PRD-0089 F1 §3.2 — per-page agents import from
 *   `@/components/primitives` (one path) rather than 14 individual files.
 *   The single import surface is the contract for cross-page reuse.
 */

export { AiContentRail } from "./AiContentRail";
export { BulkActionToolbar } from "./BulkActionToolbar";
export { DataTimestamp } from "./DataTimestamp";
export { DataFreshnessPill } from "./DataFreshnessPill";
export { DemoBadge } from "./DemoBadge";
export { DenseArticleRow } from "./DenseArticleRow";
export { EmptyState } from "./EmptyState";
export { FocusRing } from "./FocusRing";
export type { FocusRingTier } from "./FocusRing";
export { FreshnessDot } from "./FreshnessDot";
export { InlineCitationAnchor } from "./InlineCitationAnchor";
export { LoadingSkeleton } from "./LoadingSkeleton";
export { MetricCell } from "./MetricCell";
export { MetricLabel } from "./MetricLabel";
export { MetricValue } from "./MetricValue";
// Round-4 hardening: shared error.tsx body — see DESIGN_SYSTEM.md §6.7.1.
export { RouteErrorFallback } from "./RouteErrorFallback";
export type { RouteErrorFallbackProps } from "./RouteErrorFallback";
export { SectionDivider } from "./SectionDivider";
export { SeverityCharBadge } from "./SeverityCharBadge";
export { Sparkline } from "./Sparkline";
export { TableRow } from "./TableRow";
