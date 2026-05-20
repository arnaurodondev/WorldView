/**
 * components/primitives/MetricLabel.tsx — small uppercase metric label
 * (PRD-0089 F1: promoted from instrument/shared/ to cross-page primitives)
 *
 * WHY THIS EXISTS: PRD-0088 §6.11 defines one typography token for every
 * metric label (e.g. "MARKET CAP"). Centralising here means future tweaks
 * propagate everywhere — junior devs never re-hand-craft the class string.
 * WHO USES IT: every metric row / cell in Quote, Financials, Intelligence tabs.
 * DATA SOURCE: Pure presentational primitive (no data / state / effects).
 * DESIGN REFERENCE: docs/specs/0088-…-redesign.md §6.11 (Metric label row).
 * TARGET READER: junior Next.js dev (never worked in finance).
 */

import type { ReactNode } from "react";

interface MetricLabelProps {
  /** Label text (1-3 word uppercase string, e.g. "MARKET CAP"). */
  readonly children: ReactNode;
}

// WHY truncate: long labels must never wrap — rows are fixed at 22px.
export function MetricLabel({ children }: MetricLabelProps) {
  return <span className="text-[10px] uppercase tracking-wide text-muted-foreground truncate">{children}</span>;
}
