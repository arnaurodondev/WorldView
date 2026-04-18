/**
 * components/alerts/AlertsList.tsx — Paginated, filterable alert list
 *
 * WHY THIS EXISTS: The Alerts tab in app/(app)/alerts/page.tsx needs a client
 * component to hold filter state and data-fetching. Extracting it here keeps
 * the page file thin (route metadata + layout only) while the interaction logic
 * lives in a testable, reusable component.
 *
 * WHY CLIENT: useState for severity filter, useQuery for data, useRouter for
 * navigation — all require the client-side React runtime.
 *
 * WHO USES IT: app/(app)/alerts/page.tsx
 * DATA SOURCE: S9 GET /api/v1/alerts/pending (gateway.getPendingAlerts)
 * DESIGN REFERENCE: PRD-0028 §6.5 Page: Alerts & News
 */

"use client";
// WHY "use client": uses useState (filter), useQuery (data), useRouter (navigation).

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { Filter } from "lucide-react";
import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
import { SeverityBadge } from "@/components/alerts/SeverityBadge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { formatRelativeTime } from "@/lib/utils";
import type { AlertSeverity, Alert } from "@/types/api";

// ── Types ─────────────────────────────────────────────────────────────────────

/** "ALL" is a UI-only sentinel; the API only knows CRITICAL/HIGH/MEDIUM/LOW */
type SeverityFilter = "ALL" | AlertSeverity;

const SEVERITY_OPTIONS: SeverityFilter[] = ["ALL", "CRITICAL", "HIGH", "MEDIUM", "LOW"];

// ── Component ─────────────────────────────────────────────────────────────────

export function AlertsList() {
  const { accessToken } = useAuth();
  const router = useRouter();

  // ── Severity filter state ────────────────────────────────────────────────────
  // WHY local state (not URL param): filter resets naturally on tab switch,
  // which is the expected UX for a real-time alert feed.
  const [severityFilter, setSeverityFilter] = useState<SeverityFilter>("ALL");

  // ── Data fetching ────────────────────────────────────────────────────────────
  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ["alerts-pending-page", { limit: 50 }],
    queryFn: () => createGateway(accessToken).getPendingAlerts({ limit: 50 }),
    enabled: !!accessToken,
    // WHY no cache/refetch interval: alerts are real-time via WS; REST is a
    // fallback. staleTime: 0 means we always see fresh data on re-focus.
    staleTime: 0,
    refetchOnWindowFocus: true,
  });

  // ── Client-side severity filter ──────────────────────────────────────────────
  // WHY client-side (not API param): The API returns a flat list; filtering on
  // the client avoids a second network request when the user toggles the filter.
  const filteredAlerts = (data?.alerts ?? []).filter((alert) =>
    severityFilter === "ALL" ? true : alert.severity === severityFilter,
  );

  // ── Loading state ────────────────────────────────────────────────────────────
  if (isLoading) {
    return (
      <div className="space-y-2" aria-busy="true" aria-label="Loading alerts">
        {Array.from({ length: 5 }).map((_, i) => (
          <div key={i} className="flex items-center gap-3 rounded-lg border border-border/50 p-3">
            <Skeleton className="h-5 w-10" /> {/* severity badge */}
            <Skeleton className="h-4 w-16" /> {/* ticker */}
            <Skeleton className="h-4 flex-1" /> {/* message */}
            <Skeleton className="h-3 w-8" />  {/* time */}
          </div>
        ))}
      </div>
    );
  }

  // ── Error state ──────────────────────────────────────────────────────────────
  if (isError) {
    return (
      <div className="rounded-lg border border-destructive/30 bg-destructive/10 p-4 text-center">
        <p className="text-sm text-destructive">Failed to load alerts</p>
        <Button
          variant="ghost"
          size="sm"
          className="mt-2 text-xs"
          onClick={() => void refetch()}
        >
          Retry
        </Button>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {/* ── Toolbar: severity filter dropdown ─────────────────────────────── */}
      <div className="flex items-center justify-between">
        <p className="text-xs text-muted-foreground">
          {/* Show filtered count vs total for context */}
          {filteredAlerts.length} alert{filteredAlerts.length !== 1 ? "s" : ""}
          {severityFilter !== "ALL" && ` (${severityFilter})`}
          {data?.total != null && data.total > 50 && (
            <span className="ml-1">(showing first 50)</span>
          )}
        </p>

        {/* Severity filter dropdown */}
        {/* WHY DropdownMenu (not select): matches the dark-theme design system;
            native <select> doesn't inherit the Midnight Pro palette reliably. */}
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="ghost" size="sm" className="gap-1.5 text-xs">
              <Filter className="h-3 w-3" aria-hidden="true" />
              {severityFilter === "ALL" ? "All severities" : severityFilter}
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            {SEVERITY_OPTIONS.map((opt) => (
              <DropdownMenuItem
                key={opt}
                className="text-xs"
                onClick={() => setSeverityFilter(opt)}
              >
                {opt === "ALL" ? "All severities" : opt}
              </DropdownMenuItem>
            ))}
          </DropdownMenuContent>
        </DropdownMenu>
      </div>

      {/* ── Empty state ───────────────────────────────────────────────────── */}
      {filteredAlerts.length === 0 && (
        <div className="rounded-lg border border-border/50 p-8 text-center">
          <p className="text-sm text-muted-foreground">
            {severityFilter === "ALL"
              ? "No pending alerts — you're all caught up"
              : `No ${severityFilter} alerts`}
          </p>
        </div>
      )}

      {/* ── Alert rows ────────────────────────────────────────────────────── */}
      <ul className="space-y-1.5" role="list" aria-label="Alerts">
        {filteredAlerts.map((alert) => (
          <AlertRow
            key={alert.alert_id}
            alert={alert}
            onNavigate={() => {
              // Navigate to instrument detail page for the alert's entity.
              // WHY push (not href): uses Next.js client-side navigation so the
              // app shell (sidebar, topbar) stays mounted during transition.
              router.push(`/instruments/${encodeURIComponent(alert.entity_id)}`);
            }}
          />
        ))}
      </ul>
    </div>
  );
}

// ── AlertRow sub-component ────────────────────────────────────────────────────

/**
 * AlertRow — single alert item with severity badge, entity ticker, message, time.
 *
 * WHY separate from AlertsList: keeps the list map clean and the row testable
 * in isolation without mounting the full list with its query state.
 */
interface AlertRowProps {
  alert: Alert;
  onNavigate: () => void;
}

function AlertRow({ alert, onNavigate }: AlertRowProps) {
  return (
    <li>
      <button
        type="button"
        onClick={onNavigate}
        className="group flex w-full items-start gap-3 rounded-lg border border-border/50 bg-card p-3 text-left transition-colors hover:border-border hover:bg-muted/30"
        aria-label={`Alert: ${alert.title}`}
      >
        {/* Severity badge */}
        <SeverityBadge severity={alert.severity} size="sm" />

        {/* Entity ticker (if available) */}
        {alert.ticker && (
          <span className="shrink-0 font-mono text-xs tabular-nums text-primary">
            {alert.ticker}
          </span>
        )}

        {/* Alert type label */}
        <span className="shrink-0 text-xs text-muted-foreground">
          {alert.alert_type}
        </span>

        {/* Alert body — truncated at 80 chars per spec */}
        {/* WHY 80 chars: matches the task spec; longer messages cause layout
            instability in compact table rows on smaller viewports. */}
        <p
          className="min-w-0 flex-1 truncate text-xs text-foreground"
          title={alert.body}
        >
          {alert.body.length > 80 ? `${alert.body.slice(0, 77)}...` : alert.body}
        </p>

        {/* Relative timestamp — font-mono per global rule */}
        <time
          dateTime={alert.created_at}
          className="shrink-0 font-mono text-[10px] tabular-nums text-muted-foreground"
        >
          {formatRelativeTime(alert.created_at)}
        </time>
      </button>
    </li>
  );
}
