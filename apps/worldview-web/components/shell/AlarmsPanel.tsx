/**
 * components/shell/AlarmsPanel.tsx — Sidebar alert summary with severity indicators
 *
 * WHY THIS EXISTS: Institutional traders cannot afford to miss critical alerts while
 * working in a different view (e.g. reading research in the Screener while an alert
 * fires on their portfolio). The AlarmsPanel surfaces up to 5 pending alerts in the
 * sidebar so they're always in peripheral vision — similar to Bloomberg's alert rail.
 *
 * WHY max 5 rows: sidebar real estate is limited. 5 rows at 22px = 110px — enough to
 * show the day's most important alerts without drowning out the WatchlistPanel above.
 * Users needing full alert history navigate to /alerts.
 *
 * WHY severity dots (not text): 6px color-coded dots communicate severity instantly
 * without reading. A red dot signals CRITICAL before the trader reads the title.
 *
 * WHO USES IT: components/shell/CollapsibleSidebar.tsx (both collapsed + expanded)
 * DATA SOURCE: S9 GET /v1/alerts/pending (limit 20)
 * DESIGN REFERENCE: PRD-0031 §4.3 Sidebar AlarmsPanel, §0.4 Color Discipline
 */

"use client";
// WHY "use client": uses useQuery (TanStack, client-only) and useRouter for navigation.

import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
import type { Alert } from "@/types/api";

// ── Constants ─────────────────────────────────────────────────────────────────

/** Max alerts shown in the sidebar panel — more → "+N more →" link */
const MAX_ROWS = 5;

// ── Helpers ───────────────────────────────────────────────────────────────────

/**
 * severityDotClass — Tailwind class for the 6px severity indicator dot.
 * WHY toUpperCase(): S10 AlertSeverity StrEnum serialises as lowercase ("low", "high" etc.)
 * but our TypeScript type expects uppercase. Normalising here handles both cases (BP-252).
 * WHY bg-destructive for CRITICAL: the global destructive token maps to
 * --negative (#EF5350) in our palette — the correct semantic red.
 * WHY bg-warning for MEDIUM: amber conveys urgency without implying failure.
 */
function severityDotClass(severity: string): string {
  // Normalise to uppercase so lowercase S10 values ("low", "high") match (BP-252)
  const norm = severity?.toUpperCase() as Alert["severity"];
  switch (norm) {
    case "CRITICAL": return "bg-destructive";
    case "HIGH":     return "bg-negative";
    case "MEDIUM":   return "bg-warning";
    case "LOW":      return "bg-muted-foreground";
    default:         return "bg-muted-foreground";
  }
}

/**
 * timeAgo — compact relative timestamp for sidebar display.
 * WHY not absolute time: the sidebar is space-constrained. "5m" communicates
 * recency faster than "14:32:11 UTC" at 10px font size.
 * WHY cap at days (not weeks): alerts older than a few days are not "pending"
 * in any meaningful trading sense — this is a safe assumption for the sidebar.
 */
function timeAgo(isoDate: string): string {
  const diffMs = Date.now() - new Date(isoDate).getTime();
  const diffMin = Math.floor(diffMs / 60_000);
  if (diffMin < 1) return "now";
  if (diffMin < 60) return `${diffMin}m`;
  const diffHr = Math.floor(diffMin / 60);
  if (diffHr < 24) return `${diffHr}h`;
  return `${Math.floor(diffHr / 24)}d`;
}

// ── Component ─────────────────────────────────────────────────────────────────

export function AlarmsPanel() {
  const { accessToken } = useAuth();
  const router = useRouter();

  // WHY staleTime 30_000: alerts are important but not tick-level urgent in the
  // sidebar. The full /alerts page has its own SSE stream for real-time updates.
  // WHY retry: 2: changed from retry:false so transient auth failures (cold-start
  // race, brief 5xx) don't silently show an empty panel. 2 retries with 2s delay
  // gives the gateway time to recover without hanging the user for 30+ seconds.
  const { data } = useQuery({
    queryKey: ["alarms-panel"],
    queryFn: () => createGateway(accessToken).getPendingAlerts({ limit: 20 }),
    enabled: !!accessToken,
    staleTime: 30_000,
    retry: 2,
    retryDelay: 2_000,
    refetchOnMount: true,
  });

  const allAlerts = data?.alerts ?? [];
  const displayAlerts = allAlerts.slice(0, MAX_ROWS);
  const totalCount = data?.total ?? 0;
  const extraCount = Math.max(0, totalCount - MAX_ROWS);

  return (
    <div className="flex flex-col overflow-hidden">
      {/* ── Section header ────────────────────────────────────────────────── */}
      {/* WHY border-t border-b: §0.9 section header pattern — same as WatchlistPanel */}
      <div className="flex h-6 shrink-0 items-center justify-between border-b border-border border-t border-t-border px-2">
        <span className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground">
          ALARMS
        </span>
        {/* Alert count badge — only shown when there are pending alerts.
            WHY rounded-[2px]: consistent with 2px radius system (§0.3 no large radii).
            WHY bg-destructive: alerts demanding attention use the semantic error color. */}
        {totalCount > 0 && (
          <span
            className="flex h-4 items-center justify-center rounded-[2px] bg-destructive px-1 text-[10px] font-bold text-destructive-foreground"
            aria-label={`${totalCount} pending alerts`}
          >
            {totalCount > 99 ? "99+" : totalCount}
          </span>
        )}
      </div>

      {/* ── Alert rows ────────────────────────────────────────────────────── */}
      <div className="overflow-y-auto divide-y divide-border/30">
        {displayAlerts.length === 0 ? (
          // ── Empty state: short inline text per §0.5 ────────────────────────
          <p className="px-2 py-1 text-[11px] text-muted-foreground">
            No pending alerts
          </p>
        ) : (
          displayAlerts.map((alert) => (
            // WHY h-[22px]: §0.2 data table row height standard
            // WHY cursor-pointer → /alerts: sidebar rows are drill-down triggers,
            // not the primary alert surface — full detail is on /alerts
            <div
              key={alert.alert_id}
              className="flex h-[22px] items-center gap-1.5 cursor-pointer px-2 hover:bg-muted/40"
              onClick={() => router.push("/alerts")}
              aria-label={alert.title}
            >
              {/* Severity dot — 6px per PRD spec */}
              <span
                className={`h-[6px] w-[6px] shrink-0 rounded-full ${severityDotClass(alert.severity)}`}
                aria-label={`${alert.severity} severity`}
              />

              {/* Alert title — truncated to 1 line (sidebar is narrow).
                  WHY fallback chain: S10 PendingAlertResponse populates payload.message
                  rather than the legacy title/body fields (see types/api.ts Alert comment).
                  We try title first (may be populated), then payload.message, then
                  alert_type as a last resort so the row is never blank. */}
              <span className="flex-1 min-w-0 truncate text-[11px] text-foreground">
                {alert.title ||
                 String((alert.payload as { message?: string } | undefined)?.message ?? "") ||
                 alert.alert_type ||
                 "Alert"}
              </span>

              {/* Relative time — compact, monospace for alignment */}
              <span className="shrink-0 font-mono text-[10px] tabular-nums text-muted-foreground">
                {timeAgo(alert.created_at)}
              </span>
            </div>
          ))
        )}

        {/* ── Overflow link ──────────────────────────────────────────────── */}
        {extraCount > 0 && (
          <button
            onClick={() => router.push("/alerts")}
            className="w-full px-2 py-0.5 text-left text-[10px] text-muted-foreground hover:text-foreground transition-colors duration-0"
          >
            +{extraCount} more →
          </button>
        )}
      </div>
    </div>
  );
}
