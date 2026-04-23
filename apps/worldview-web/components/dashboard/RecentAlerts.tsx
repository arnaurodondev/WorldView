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
        combined.push({
          id: a.alert_id,
          severity: a.severity,
          alert_type: a.alert_type,
          entity_id: a.entity_id,
          message: a.body,
          created_at: a.created_at,
        });
      }
    }

    // Sort newest first, limit to 8 rows
    return combined
      .sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime())
      .slice(0, 8);
  }, [recentAlerts, alertsResp?.alerts]);

  // ── Loading state ──────────────────────────────────────────────────────────
  if (isLoading && merged.length === 0) {
    return (
      <div className="space-y-2">
        {Array.from({ length: 3 }).map((_, i) => (
          <div key={i} className="flex gap-2">
            <Skeleton className="h-5 w-12" style={{ animationDelay: `${i * 50}ms` }} />
            <Skeleton className="h-5 flex-1" style={{ animationDelay: `${i * 50}ms` }} />
          </div>
        ))}
      </div>
    );
  }

  // ── Empty state ────────────────────────────────────────────────────────────
  if (merged.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">No recent alerts</p>
    );
  }

  return (
    <div className="space-y-1">
      {merged.map((alert) => {
        const { text: severityText, bg: severityBg } = severityColor(alert.severity);
        const timeStr = relativeTime(alert.created_at);

        return (
          <div
            key={alert.id}
            className="flex items-start gap-2 rounded px-1 py-0.5 hover:bg-muted/30"
          >
            {/* Severity badge — use Tailwind bg/text classes from severityColor */}
            <span
              className={`shrink-0 rounded px-1 py-0.5 text-[9px] font-semibold uppercase tracking-wider ${severityBg} ${severityText}`}
            >
              {alert.severity.slice(0, 4)}
            </span>

            {/* Alert message */}
            <p className="min-w-0 flex-1 truncate text-xs text-foreground" title={alert.message}>
              {alert.message}
            </p>

            {/* Timestamp */}
            <span className="shrink-0 font-mono text-[10px] tabular-nums text-muted-foreground">
              {timeStr}
            </span>
          </div>
        );
      })}

      {/* View all link */}
      <Link
        href="/alerts"
        className="mt-1 block text-center text-xs text-muted-foreground hover:text-foreground"
      >
        View all alerts →
      </Link>
    </div>
  );
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function relativeTime(isoStr: string): string {
  const diffMs = Date.now() - new Date(isoStr).getTime();
  const diffMin = Math.floor(diffMs / 60_000);
  if (diffMin < 1) return "now";
  if (diffMin < 60) return `${diffMin}m`;
  return `${Math.floor(diffMin / 60)}h`;
}
