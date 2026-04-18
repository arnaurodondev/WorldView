/**
 * components/alerts/SeverityBadge.tsx — Alert severity level badge
 *
 * WHY THIS EXISTS: Alert severity (CRITICAL / HIGH / MEDIUM / LOW) is shown in
 * at least 4 places: the Alerts page list, the Sidebar recent-alerts section,
 * the FlashOverlay, and dashboard RecentAlerts widget. A shared badge ensures
 * the colour coding is identical everywhere — traders build pattern recognition
 * around visual severity cues and inconsistency breaks that fast-scan workflow.
 *
 * WHO USES IT: AlertsList (alerts page), app/(app)/alerts/page.tsx,
 * Sidebar recent-alerts, dashboard RecentAlerts.
 *
 * DATA SOURCE: AlertSeverity type from types/api.ts
 * DESIGN REFERENCE: PRD-0028 §6.5 alerts components, badge.tsx variants
 */

// WHY no "use client": pure presentational, no hooks, no browser APIs.
// Can be used in Server Components or imported into client components.

import { Badge } from "@/components/ui/badge";
import { severityColor } from "@/lib/utils";
import type { AlertSeverity } from "@/types/api";

// ── Props ─────────────────────────────────────────────────────────────────────

interface SeverityBadgeProps {
  severity: AlertSeverity;
  /** Optional size variant — "sm" for compact rows, "default" for larger displays */
  size?: "sm" | "default";
}

// ── Severity label map ────────────────────────────────────────────────────────
// WHY abbreviated labels: "CRIT" / "HIGH" / "MED" / "LOW" fit in compact table
// rows without overflow. Full labels are available via aria-label for screenreaders.
const SEVERITY_LABEL: Record<AlertSeverity, string> = {
  CRITICAL: "CRIT",
  HIGH: "HIGH",
  MEDIUM: "MED",
  LOW: "LOW",
};

// ── Component ─────────────────────────────────────────────────────────────────

/**
 * SeverityBadge — compact severity indicator using Midnight Pro palette colours.
 *
 * WHY custom className over Badge variant: The Badge component has default/secondary/
 * destructive/warning/positive variants, but severity needs four distinct states.
 * We apply the severity-specific bg and text classes from severityColor() directly.
 */
export function SeverityBadge({ severity, size = "default" }: SeverityBadgeProps) {
  // WHY severityColor utility: centralises the color logic so both this component
  // and the inline severity spans in RecentAlerts widget stay in sync automatically.
  const { bg, text } = severityColor(severity);

  return (
    <Badge
      // Override badge base with severity-specific palette classes
      className={`${bg} ${text} border-0 font-mono tracking-wider ${
        size === "sm" ? "px-1 py-0 text-[9px]" : "px-1.5 py-0.5 text-[10px]"
      }`}
      // Full severity label for screenreaders — abbreviated label in visual
      aria-label={severity}
    >
      {SEVERITY_LABEL[severity]}
    </Badge>
  );
}
