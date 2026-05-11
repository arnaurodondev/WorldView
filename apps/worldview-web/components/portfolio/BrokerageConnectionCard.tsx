/**
 * components/portfolio/BrokerageConnectionCard.tsx — Single brokerage connection card
 *
 * WHY THIS EXISTS: ConnectedBrokeragesList renders multiple connections; this
 * component handles the display and actions for one. Extracting it allows the
 * list to stay simple (iteration only) while the card handles:
 *   - Status badge (● ACTIVE / PENDING / ERROR / DISCONNECTED)
 *   - Sync Now → POST trigger
 *   - Sync error expansion (inline list of error_type + error_detail)
 *   - Disconnect → confirm + DELETE
 *
 * WHY status badge uses a colored dot (●): Bloomberg terminal uses colored
 * status indicators for system state. A dot is instantly parseable at a glance —
 * no need to read text to know if the connection is healthy.
 *
 * WHO USES IT: components/brokerage/ConnectedBrokeragesList.tsx (list iterator)
 * DATA SOURCE: BrokerageConnection from S9 + SyncErrors via expand
 * DESIGN REFERENCE: PRD-0031 §8.6 Brokerage Connection Card, Wave 4
 */

"use client";
// WHY "use client": useState for expand/collapse of sync errors.

import { useState } from "react";
import { cn } from "@/lib/utils";
import { formatDateTime } from "@/lib/utils";
import type { BrokerageConnection, SyncError } from "@/types/api";

// ── Types ─────────────────────────────────────────────────────────────────────

export interface BrokerageConnectionCardProps {
  connection: BrokerageConnection;
  /** Optional sync errors for this connection (loaded on expand) */
  syncErrors?: SyncError[];
  /** Whether sync errors are currently loading */
  syncErrorsLoading?: boolean;
  /** Called when user clicks "Sync Now" */
  onSync?: (connectionId: string) => void;
  /** Whether a sync is in progress for this connection */
  isSyncing?: boolean;
  /** Called when user confirms disconnect */
  onDisconnect?: (connectionId: string) => void;
  /** Called when user requests sync errors (triggers load) */
  onRequestSyncErrors?: (connectionId: string) => void;
}

// ── Status badge ──────────────────────────────────────────────────────────────

type ConnectionStatus = BrokerageConnection["status"];

function statusConfig(status: ConnectionStatus): {
  dot: string;
  label: string;
  text: string;
} {
  switch (status) {
    case "active":
      return { dot: "bg-positive", label: "ACTIVE", text: "text-positive" };
    case "pending":
      return { dot: "bg-warning", label: "PENDING", text: "text-warning" };
    case "error":
      return { dot: "bg-negative", label: "ERROR", text: "text-negative" };
    case "disconnected":
      return { dot: "bg-muted-foreground", label: "DISCONNECTED", text: "text-muted-foreground" };
    default:
      return { dot: "bg-muted-foreground", label: String(status).toUpperCase(), text: "text-muted-foreground" };
  }
}

// ── BrokerageConnectionCard ───────────────────────────────────────────────────

export function BrokerageConnectionCard({
  connection,
  syncErrors,
  syncErrorsLoading,
  onSync,
  isSyncing,
  onDisconnect,
  onRequestSyncErrors,
}: BrokerageConnectionCardProps) {
  // WHY local state: sync error expansion is per-card UI state, not global.
  const [errorsExpanded, setErrorsExpanded] = useState(false);
  const [confirmDisconnect, setConfirmDisconnect] = useState(false);

  const { dot, label, text } = statusConfig(connection.status);
  const errorCount = syncErrors?.length ?? 0;

  function handleToggleErrors() {
    if (!errorsExpanded && onRequestSyncErrors) {
      onRequestSyncErrors(connection.connection_id);
    }
    setErrorsExpanded((v) => !v);
  }

  function handleDisconnect() {
    if (!confirmDisconnect) {
      // WHY two-click confirm: DELETE is destructive. The first click sets a
      // "confirm" state that changes the button label to "Confirm?" — a second
      // click is required. This prevents accidental disconnects.
      setConfirmDisconnect(true);
      return;
    }
    onDisconnect?.(connection.connection_id);
    setConfirmDisconnect(false);
  }

  return (
    // WHY border (not rounded-lg card): terminal quality — cards use 1px borders,
    // not shadows or large rounded corners.
    <div className="border border-border rounded-[2px] overflow-hidden">
      {/* ── Card header ──────────────────────────────────────────────────── */}
      <div className="flex h-9 items-center gap-2 px-3 border-b border-border bg-card">
        {/* Status dot */}
        <span className={cn("h-1.5 w-1.5 rounded-full shrink-0", dot)} aria-hidden />

        {/* Brokerage name */}
        <span className="font-mono text-[11px] font-medium text-foreground truncate flex-1">
          {connection.brokerage_name ?? "Unknown Brokerage"}
        </span>

        {/* Status label */}
        <span className={cn("font-mono text-[10px] uppercase tracking-[0.06em] shrink-0", text)}>
          {label}
        </span>
      </div>

      {/* ── Card body ────────────────────────────────────────────────────── */}
      <div className="px-3 py-2 space-y-2">
        {/* Last synced timestamp */}
        <div className="flex items-center justify-between text-[10px]">
          <span className="text-muted-foreground uppercase tracking-[0.06em]">Last sync</span>
          <span className="font-mono tabular-nums text-foreground">
            {connection.last_synced_at
              ? formatDateTime(connection.last_synced_at)
              : "Never"}
          </span>
        </div>

        {/* Action buttons */}
        <div className="flex items-center gap-2">
          {/* Sync Now — only available for active connections */}
          {connection.status === "active" && (
            <button
              aria-label="Sync brokerage now"
              disabled={isSyncing}
              onClick={() => onSync?.(connection.connection_id)}
              className={cn(
                "h-6 px-2 text-[10px] font-mono uppercase tracking-[0.06em] border rounded-[2px] transition-colors",
                isSyncing
                  ? "border-border text-muted-foreground cursor-wait"
                  : "border-primary/60 text-primary hover:bg-primary/10",
              )}
            >
              {isSyncing ? "Syncing…" : "Sync Now"}
            </button>
          )}

          {/* Sync Errors count — expands inline error list */}
          <button
            aria-label={`${errorCount} sync errors — click to ${errorsExpanded ? "collapse" : "expand"}`}
            aria-expanded={errorsExpanded}
            onClick={handleToggleErrors}
            className={cn(
              "h-6 px-2 text-[10px] font-mono uppercase tracking-[0.06em] border rounded-[2px] transition-colors",
              errorCount > 0
                ? "border-negative/60 text-negative hover:bg-negative/10"
                : "border-border text-muted-foreground",
            )}
          >
            {syncErrorsLoading ? "…" : `Errors (${errorCount})`}
          </button>

          {/* Disconnect — two-click confirm */}
          <button
            aria-label={confirmDisconnect ? "Confirm disconnect" : "Disconnect brokerage"}
            onClick={handleDisconnect}
            className={cn(
              "ml-auto h-6 px-2 text-[10px] font-mono uppercase tracking-[0.06em] border rounded-[2px] transition-colors",
              confirmDisconnect
                ? "border-negative/60 text-negative hover:bg-negative/10"
                : "border-border text-muted-foreground hover:text-foreground",
            )}
          >
            {confirmDisconnect ? "Confirm?" : "Disconnect"}
          </button>
        </div>

        {/* ── Sync error list (expanded) ──────────────────────────────── */}
        {errorsExpanded && (
          // F-P-023 (PLAN-0051 W6): use ``border-border/60`` for soft
          // intra-card section dividers — full opacity ``border-border``
          // is reserved for between-panel separators (where strong
          // visual divisions are needed). Inside one card the softer
          // 60% alpha reads as "separator within the same surface".
          <div className="border-t border-border/60 pt-2 space-y-1">
            {syncErrorsLoading ? (
              <p className="text-[10px] text-muted-foreground">Loading errors…</p>
            ) : errorCount === 0 ? (
              <p className="text-[10px] text-muted-foreground">No sync errors.</p>
            ) : (
              syncErrors?.map((err) => (
                <div
                  key={err.id}
                  className="flex items-start gap-2 text-[10px]"
                >
                  {/* WHY text-negative bullet: these are error records, always negative */}
                  <span className="text-negative mt-0.5 shrink-0">●</span>
                  <div className="min-w-0">
                    <span className="font-mono text-muted-foreground uppercase tracking-[0.04em]">
                      {err.error_type}
                    </span>
                    {err.error_detail && (
                      <span className="ml-2 text-foreground">{err.error_detail}</span>
                    )}
                  </div>
                </div>
              ))
            )}
          </div>
        )}
      </div>
    </div>
  );
}
