/**
 * components/dashboard/RecentAlerts.tsx — Live + historical alert feed widget
 *
 * WHY THIS EXISTS: Alerts are time-sensitive by definition. Showing them
 * prominently on the dashboard means traders see critical signals without
 * navigating to the dedicated Alerts page. This widget combines:
 * - Live stream: recentAlerts from AlertStreamContext (realtime WebSocket)
 * - Historical: GET /v1/alerts/pending (polled every 30s, catches missed WebSocket events)
 *
 * WHY COMBINE BOTH: WebSocket reconnects lose messages. The REST poll fills gaps.
 * Deduplication by alert_id ensures no visual duplicates.
 *
 * WHO USES IT: app/(app)/dashboard/page.tsx
 * DATA SOURCE: AlertStreamContext.recentAlerts + S9 GET /api/v1/alerts?acknowledged=false
 * DESIGN REFERENCE: PRD-0028 §6.5 Dashboard RecentAlerts
 */

"use client";
// WHY "use client": uses useAlertStream (context), useQuery.

import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
import { useAlertStream } from "@/contexts/AlertStreamContext";
import { severityColor } from "@/lib/utils";
import { formatAlertTitle } from "@/lib/alerts/format";
import { Skeleton } from "@/components/ui/skeleton";
import type { AlertPayload } from "@/types/alerts";

// ── Component ─────────────────────────────────────────────────────────────────

export function RecentAlerts() {
  const { accessToken } = useAuth();
  const { recentAlerts } = useAlertStream();

  // ── Poll historical alerts from REST endpoint ──────────────────────────────
  // WHY poll: WebSocket gaps could miss alerts. REST is the authoritative source.
  const { data: alertsResp, isLoading } = useQuery({
    queryKey: ["alerts-pending"],
    queryFn: () => createGateway(accessToken).getPendingAlerts({ limit: 10 }),
    enabled: !!accessToken,
    refetchInterval: 30_000, // WHY 30s: balance freshness vs API load
    staleTime: 15_000,
  });

  // ── Merge live + historical, deduplicating by alert_id ────────────────────
  const merged = useMemo(() => {
    const seen = new Set<string>();
    const combined: AlertPayload[] = [];

    // Live alerts first (most recent)
    for (const a of recentAlerts) {
      if (!seen.has(a.id)) {
        seen.add(a.id);
        combined.push(a);
      }
    }

    // WHY REST alerts converted to AlertPayload shape: AlertPayload and Alert
    // have overlapping but not identical shapes. Map to common structure.
    for (const a of alertsResp?.alerts ?? []) {
      if (!seen.has(a.alert_id)) {
        seen.add(a.alert_id);
        // PLAN-0049 T-D-4-04: shared fallback ladder lives in lib/alerts/format
        // so RecentAlerts and AlarmsPanel can't drift. The formatter NEVER
        // returns bare "<SEVERITY> signal" strings (regression: F-D-006/F-X-201).
        const message = formatAlertTitle(a);
        combined.push({
          id: a.alert_id,
          // WHY toUpperCase(): S10 AlertSeverity StrEnum returns lowercase ("low", "critical").
          // AlertPayload.severity expects uppercase. Normalise to match severityColor() cases.
          severity: (a.severity?.toUpperCase() ?? "LOW") as AlertPayload["severity"],
          alert_type: a.alert_type,
          entity_id: a.entity_id ?? null,
          message,
          created_at: a.created_at,
        });
      }
    }

    // Sort newest first, limit to 8 rows
    return combined
      .sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime())
      .slice(0, 8);
  }, [recentAlerts, alertsResp?.alerts]);

  // WHY single outer wrapper for all render paths: consistent bg-background + h-full
  // across all Row-4 panels regardless of data state. See EconomicCalendar for rationale.
  return (
    <div className="flex h-full flex-col bg-background">

      {/* ── Section header §0.9 pattern ──────────────────────────────────── */}
      <div className="flex h-6 shrink-0 items-center border-b border-border px-2">
        <span className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground">
          RECENT ALERTS
        </span>
      </div>

      {/* ── Loading state ──────────────────────────────────────────────── */}
      {isLoading && merged.length === 0 && (
        <div className="flex-1 space-y-2 px-2 pt-1">
          {Array.from({ length: 3 }).map((_, i) => (
            <div key={i} className="flex gap-2">
              <Skeleton className="h-5 w-12" style={{ animationDelay: `${i * 50}ms` }} />
              <Skeleton className="h-5 flex-1" style={{ animationDelay: `${i * 50}ms` }} />
            </div>
          ))}
        </div>
      )}

      {/* ── Empty state ─────────────────────────────────────────────────── */}
      {/* WHY descriptive message (not "No recent alerts"): the empty state may confuse
          new traders into thinking alerts are disabled. Telling them where to create
          alert rules guides them to the action that will populate this widget.
          The second line is a softer hint about where to go — not an error state. */}
      {!isLoading && merged.length === 0 && (
        <div className="flex flex-1 flex-col gap-0.5 px-2 pt-2">
          <p className="text-xs text-muted-foreground">No recent alerts.</p>
          <p className="text-[10px] text-muted-foreground/60">
            Create alert rules on the{" "}
            <a href="/alerts" className="text-primary hover:underline">Alerts page</a>
            {" "}to receive notifications here.
          </p>
        </div>
      )}

      {/* ── Alert rows ──────────────────────────────────────────────────── */}
      {merged.length > 0 && (
        <div className="flex-1 divide-y divide-border/30 overflow-auto">
          {merged.map((alert) => {
            const { text: severityText, bg: severityBg } = severityColor(alert.severity);
            const timeStr = relativeTime(alert.created_at);
            // F-301 defensive follow-up: even though AlertStreamContext now
            // aliases alert_id → id, REST-sourced alerts may still arrive
            // without an id in pathological cases. Guard the href so we
            // never emit `?selected=undefined` again. Falling back to
            // `/alerts` (no selection) keeps the row navigable as a
            // generic "open alerts page" link.
            const href = alert.id
              ? `/alerts?selected=${encodeURIComponent(alert.id)}`
              : "/alerts";

            return (
              // WHY <Link>: users expect clicking an alert row to navigate to the
              // Alerts page — the hover state implies interactivity. Wrapping in
              // Link makes the entire row a navigation target (BP-263 follow-up).
              // PLAN-0048 Wave B-3: deep-link to ?selected={id} so the AlertsList
              // page opens the AlertDetailSheet automatically — much faster path
              // to "see the full payload" than landing on the list and clicking.
              <Link
                key={alert.id || `${alert.created_at}-${alert.alert_type}`}
                href={href}
                // WHY h-[22px]: terminal row height per §0 Terminal CLI Quality Standard
                className="flex h-[22px] items-center gap-2 px-2 py-0 hover:bg-muted/40 no-underline"
              >
                {/* Severity badge — use Tailwind bg/text classes from severityColor */}
                <span
                  // WHY rounded-[2px]: design system mandates 2px radius everywhere; bare `rounded` = 4px default
                  className={`shrink-0 rounded-[2px] px-1 py-0.5 text-[9px] font-semibold uppercase tracking-wider ${severityBg} ${severityText}`}
                >
                  {alert.severity.slice(0, 4)}
                </span>

                {/* Alert message */}
                <p className="min-w-0 flex-1 truncate text-[11px] text-foreground" title={alert.message}>
                  {alert.message}
                </p>

                {/* Timestamp */}
                <span className="shrink-0 font-mono text-[10px] tabular-nums text-muted-foreground">
                  {timeStr}
                </span>
              </Link>
            );
          })}
        </div>
      )}

      {/* ── Footer: view all link ────────────────────────────────────────── */}
      {/* WHY always show (not only when data): the Alerts page is always reachable
          regardless of whether there are current alerts. A persistent link improves
          discoverability for new users who haven't seen alerts before. */}
      <div className="shrink-0 border-t border-border/30 px-2 py-0.5">
        <Link
          href="/alerts"
          className="text-[11px] text-muted-foreground hover:text-foreground"
        >
          View all alerts →
        </Link>
      </div>

    </div>
  );
}

// ── Helpers ───────────────────────────────────────────────────────────────────

/**
 * relativeTime — "5m" / "3h" / "now" for the alert timestamp slot.
 *
 * F-303 fix (PLAN-0048 QA iter-1): WS-sourced alerts may arrive without a
 * `created_at` (or with a malformed ISO string), in which case
 * `new Date(undefined).getTime()` returns NaN. The previous implementation
 * subtracted that NaN from Date.now() and string-concatenated the result,
 * producing visible "NaNh" timestamps in the dashboard alerts feed.
 *
 * We now guard against:
 *   1. Empty/missing isoStr → "—"
 *   2. Date that fails to parse (Number.isNaN on .getTime()) → "—"
 *   3. Future timestamps (negative diff from clock skew) → "now"
 */
function relativeTime(isoStr: string | null | undefined): string {
  if (!isoStr) return "—";
  const t = new Date(isoStr).getTime();
  if (!Number.isFinite(t)) return "—";
  const diffMs = Date.now() - t;
  // Future (e.g. clock skew) → display as "now" rather than a negative count
  if (diffMs < 0) return "now";
  const diffMin = Math.floor(diffMs / 60_000);
  if (diffMin < 1) return "now";
  if (diffMin < 60) return `${diffMin}m`;
  return `${Math.floor(diffMin / 60)}h`;
}
