/**
 * components/primitives/SeverityCharBadge.tsx — 1-char severity glyph
 *
 * WHY THIS EXISTS: PRD-0089 F1 §3.2 — alert severity in dense rows must
 * occupy ≤1 column of space.  A 1-char glyph + color encoding lets each
 * Alerts row stay 20px tall and 1 char wide for severity while still
 * conveying critical / high / med / low at a glance.  Bloomberg/Eikon
 * use the same single-char convention in OMS panels.
 * WHO USES IT: Dashboard alerts widget, Intelligence severity column,
 *   alerts inbox.
 * DATA SOURCE: Caller passes severity (typically from /v1/alerts severity
 *   field). Pure presentational.
 * DESIGN REFERENCE: PRD-0089 F1 §3.2 (SeverityCharBadge row).
 */

import type { ReactNode } from "react";

type Severity = "critical" | "high" | "med" | "low";

interface SeverityCharBadgeProps {
  readonly severity: Severity;
}

// WHY the glyph map: "!" reads as urgent across keyboards & locales,
// "*" is mid-attention, "·" is a small bullet, " " preserves column width
// for low-priority rows without leaving the column visually empty.
const GLYPH: Record<Severity, string> = {
  critical: "!",
  high: "*",
  med: "·",
  low: " ",
};

const COLOR: Record<Severity, string> = {
  critical: "text-destructive",
  high: "text-warning",
  med: "text-muted-foreground",
  low: "text-muted-foreground/50",
};

export function SeverityCharBadge({ severity }: SeverityCharBadgeProps): ReactNode {
  return (
    <span
      role="img"
      aria-label={`severity ${severity}`}
      className={`inline-block w-[1ch] font-mono ${COLOR[severity]}`}
    >
      {GLYPH[severity]}
    </span>
  );
}
