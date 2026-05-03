/**
 * components/alerts/alert-history-columns.tsx — ColumnDef array for AlertHistoryTab
 *
 * WHY THIS EXISTS: Extracted from AlertHistoryTab so the column definitions
 * (cell renderers, badge helpers, status logic) can be unit-tested in isolation
 * and reused if the same table shape ever appears in a different surface.
 *
 * WHO USES IT: AlertHistoryTab → DataTable primitive.
 * DATA SOURCE: GET /v1/alerts/history via getAlertHistory().
 * DESIGN REFERENCE: PLAN-0059 F-1 (DataTable migration).
 */

import type { ColumnDef } from "@tanstack/react-table";
import { cn, formatRelativeTime } from "@/lib/utils";
import type { Alert, AlertSeverity } from "@/types/api";

// ── Helpers (moved from AlertHistoryTab, exported for tests) ──────────────────

/** Derive display status from alert fields. "ack" wins over "snoozed" over "active". */
export function computeStatus(alert: Alert): "active" | "ack" | "snoozed" {
  if (alert.acknowledged_at) return "ack";
  const snoozeUntil = alert.snooze_until ? new Date(alert.snooze_until).getTime() : 0;
  if (snoozeUntil && snoozeUntil > Date.now()) return "snoozed";
  return "active";
}

export const SEVERITY_PILL_CLASS: Record<AlertSeverity, string> = {
  CRITICAL: "bg-negative/20 text-negative",
  HIGH: "bg-warning/20 text-warning",
  MEDIUM: "bg-primary/15 text-primary",
  LOW: "bg-muted/40 text-muted-foreground",
};

export const STATUS_PILL_CLASS: Record<"active" | "ack" | "snoozed", string> = {
  active: "bg-primary/15 text-primary",
  ack: "bg-muted/40 text-muted-foreground",
  snoozed: "bg-warning/20 text-warning",
};

// ── Column definitions ────────────────────────────────────────────────────────

/**
 * alertHistoryColumns — 6 columns matching the original AlertHistoryTab table.
 * onRowClick is passed to DataTable separately; the Type cell is plain text
 * because clicking anywhere on the row (DataTable onRowClick) handles navigation.
 */
export const alertHistoryColumns: ColumnDef<Alert>[] = [
  {
    id: "severity",
    accessorKey: "severity",
    header: "Severity",
    size: 90,
    cell: ({ row }) => {
      const sevKey = ((row.original.severity ?? "").toUpperCase() || "LOW") as AlertSeverity;
      return (
        <span
          className={cn(
            "inline-block rounded-[2px] px-1 text-[9px] uppercase tracking-[0.08em]",
            SEVERITY_PILL_CLASS[sevKey],
          )}
        >
          {sevKey}
        </span>
      );
    },
  },
  {
    id: "ticker",
    accessorKey: "ticker",
    header: "Ticker",
    size: 80,
    cell: ({ row }) => (
      // WHY font-mono tabular-nums: ticker symbols are fixed-width identifiers;
      // monospace ensures they align across rows when scanning the list quickly.
      <span className="font-mono tabular-nums">{row.original.ticker ?? "—"}</span>
    ),
  },
  {
    id: "alert_type",
    accessorKey: "alert_type",
    header: "Type",
    size: 140,
    cell: ({ row }) => (
      // WHY plain text (not a <button>): DataTable's onRowClick handles
      // navigation for the whole row. A nested button would fire both its
      // onClick and the row's onClick, causing double navigation.
      <span className="text-foreground">{row.original.alert_type}</span>
    ),
  },
  {
    id: "created_at",
    accessorKey: "created_at",
    header: "Fired",
    size: 100,
    cell: ({ row }) => (
      <span className="font-mono tabular-nums text-muted-foreground" title={row.original.created_at}>
        {formatRelativeTime(row.original.created_at)}
      </span>
    ),
  },
  {
    id: "acknowledged_at",
    accessorKey: "acknowledged_at",
    header: "Dismissed",
    size: 100,
    cell: ({ row }) =>
      row.original.acknowledged_at ? (
        <span
          className="font-mono tabular-nums text-muted-foreground"
          title={row.original.acknowledged_at}
        >
          {formatRelativeTime(row.original.acknowledged_at)}
        </span>
      ) : (
        <span className="text-muted-foreground">—</span>
      ),
  },
  {
    id: "status",
    header: "Status",
    size: 80,
    // WHY no accessorKey: "status" is not a field on Alert — it is computed
    // from acknowledged_at and snooze_until. The cell renderer calls
    // computeStatus() directly.
    enableSorting: false,
    cell: ({ row }) => {
      const status = computeStatus(row.original);
      return (
        <span
          className={cn(
            "rounded-[2px] px-1 text-[9px] uppercase tracking-[0.08em]",
            STATUS_PILL_CLASS[status],
          )}
        >
          {status}
        </span>
      );
    },
  },
];
