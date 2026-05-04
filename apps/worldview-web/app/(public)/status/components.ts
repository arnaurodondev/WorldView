/**
 * app/(public)/status/components.ts — monitor-to-Sam-facing label mapping
 *
 * WHY THIS EXISTS:
 * UptimeRobot monitor names like "API Gateway — liveness" are internal
 * architecture terms that mean nothing to an analyst. This mapping converts
 * raw monitor friendly_names into labels Sam actually understands.
 *
 * WHY A STATIC MAP (not dynamic): The set of monitors is small and changes
 * only when we add new monitors (a deliberate ops action). A static map keeps
 * the page rendering fast (no extra round-trips) and makes the label choices
 * explicit and reviewable.
 *
 * HOW TO ADD A MONITOR:
 *   1. Create the monitor in UptimeRobot.
 *   2. Add an entry here: friendly_name → component_label.
 *   3. The status page auto-renders the new pill.
 *
 * PLAN-0065 T-E-02, PRD-0034 §3 FR-T3-1
 */

/**
 * Maps UptimeRobot `friendly_name` values → user-facing component labels.
 *
 * Keys are substrings matched case-insensitively against the monitor's
 * friendly_name so minor name changes in UptimeRobot don't break the map.
 * First matching key wins.
 */
export const MONITOR_LABEL_MAP: Record<string, string> = {
  // Liveness monitor (/healthz) — process-up signal
  liveness: "Platform",
  healthz: "Platform",

  // Readiness monitor (/readyz) — dependency health (Valkey, etc.)
  readiness: "Caching & rate limits",
  readyz: "Caching & rate limits",

  // Future monitors (light up when W5 / W6 land their dedicated probes)
  search: "Search",
  brief: "AI Briefs",
};

/**
 * Resolve the Sam-facing label for a monitor, given its friendly_name.
 * Falls back to the raw friendly_name if no mapping matches.
 */
export function resolveComponentLabel(friendlyName: string): string {
  const lower = friendlyName.toLowerCase();
  for (const [key, label] of Object.entries(MONITOR_LABEL_MAP)) {
    if (lower.includes(key)) return label;
  }
  // Unknown monitor — display raw name rather than hiding it
  return friendlyName;
}

/**
 * UptimeRobot numeric status codes.
 * 2 = up, 9 = down, 8 = seems down (intermittent), 0 = paused.
 */
export type MonitorStatus = 0 | 2 | 8 | 9;

/** Whitelisted monitor shape returned by the /api/uptime Route Handler. */
export interface MonitorSummary {
  monitor_id: number;
  friendly_name: string;
  component_label: string;
  status: MonitorStatus;
  custom_uptime_ratio: string; // e.g. "99.97"
  daily_buckets: Array<{ date: string; up: boolean }>; // 30 entries
}

/** Incident shape from incidents.json */
export interface Incident {
  title: string;
  severity: "info" | "warn" | "critical";
  started_at: string; // ISO-8601
  resolved_at: string | null; // null = ongoing
}

/** Full payload returned by /api/uptime */
export interface UptimePayload {
  monitors: MonitorSummary[];
  incidents: Incident[];
}

/** Translate numeric status to a human label and Tailwind color class. */
export function statusInfo(status: MonitorStatus): {
  label: string;
  colorClass: string;
} {
  switch (status) {
    case 2:
      return { label: "Operational", colorClass: "bg-green-500" };
    case 8:
      return { label: "Degraded", colorClass: "bg-amber-500" };
    case 9:
      return { label: "Down", colorClass: "bg-red-500" };
    case 0:
      return { label: "Paused", colorClass: "bg-zinc-500" };
    default:
      return { label: "Unknown", colorClass: "bg-zinc-500" };
  }
}
