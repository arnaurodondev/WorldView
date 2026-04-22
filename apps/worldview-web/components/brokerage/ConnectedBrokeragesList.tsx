/**
 * ConnectedBrokeragesList — list of SnapTrade brokerage connections for a portfolio
 *
 * WHY THIS EXISTS: The Portfolio page's Brokerages tab needs a component that
 * shows all active/pending/error connections for the selected portfolio, lets
 * the user trigger a manual re-sync, and disconnect brokerages they no longer
 * want. Extracting this into its own component keeps the portfolio page lean
 * and makes the brokerage list independently testable.
 *
 * STATES:
 *   Loading  → skeleton rows (prevents CLS while data loads)
 *   Error    → inline error banner with descriptive message
 *   Empty    → call-to-action copy directing user to Connect Brokerage button
 *   Loaded   → one row per connection with status badge + action buttons
 *
 * WHY SYNC NOW for active AND error:
 *   Active — user may want to pull latest transactions on demand
 *   Error  — re-sync is how the user recovers from a transient error; if the
 *             underlying issue is fixed (e.g., broker API back online) a sync
 *             attempt may succeed and clear the error status.
 *
 * WHO USES IT: app/(app)/portfolio/page.tsx — Brokerages tab content
 * DATA SOURCE: hooks/use-brokerage-connections.ts
 * DESIGN REFERENCE: PRD-0022 §6.6
 */

"use client";
// WHY "use client": useBrokerageConnections (useQuery), useTriggerBrokerageSync,
// useDisconnectBrokerageConnection (useMutation) all require client-side React runtime.

import { useState } from "react";
import {
  RefreshCw,
  Loader2,
  Trash2,
  AlertCircle,
  CheckCircle2,
  Clock,
  WifiOff,
  Link2,
} from "lucide-react";
import {
  useBrokerageConnections,
  useDisconnectBrokerageConnection,
  useTriggerBrokerageSync,
} from "@/hooks/use-brokerage-connections";
import { SyncErrorsBanner } from "@/components/brokerage/SyncErrorsBanner";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import type { BrokerageConnection } from "@/types/api";

// ── Helpers ───────────────────────────────────────────────────────────────────

/**
 * formatLastSynced — human-readable "last synced" label
 *
 * WHY a helper (not inline): the formatting logic is used in each connection row.
 * Extracting it makes the row JSX cleaner and the logic independently testable.
 */
function formatLastSynced(lastSyncedAt: string | null): string {
  if (!lastSyncedAt) return "Never synced";

  const date = new Date(lastSyncedAt);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffMins = Math.floor(diffMs / 60_000);

  // WHY relative time for recent syncs: "2 minutes ago" is more informative
  // than "2026-04-22T14:32:00Z" for a professional user monitoring sync freshness.
  if (diffMins < 1) return "Just now";
  if (diffMins < 60) return `${diffMins}m ago`;
  const diffHours = Math.floor(diffMins / 60);
  if (diffHours < 24) return `${diffHours}h ago`;
  const diffDays = Math.floor(diffHours / 24);
  return `${diffDays}d ago`;
}

/**
 * StatusBadge — color-coded pill for connection status
 *
 * WHY Midnight Pro palette for status colors:
 *   active      → #26A69A (bull green)  — everything working
 *   error       → #EF5350 (bear red)    — attention required
 *   pending     → amber                 — waiting, not yet usable
 *   disconnected → muted gray           — inactive, informational
 *
 * Using inline style for the exact hex values so they survive Tailwind purge
 * (dynamic class names wouldn't be included in the production CSS bundle).
 */
function StatusBadge({ status }: { status: BrokerageConnection["status"] }) {
  const configs = {
    active: {
      icon: <CheckCircle2 className="h-3 w-3" aria-hidden="true" />,
      label: "ACTIVE",
      // WHY style not className: exact hex colours aren't in tailwind config;
      // style prop bypasses Tailwind purge for these one-off design tokens.
      style: { color: "#26A69A", borderColor: "rgba(38,166,154,0.3)", backgroundColor: "rgba(38,166,154,0.1)" } as React.CSSProperties,
    },
    error: {
      icon: <AlertCircle className="h-3 w-3" aria-hidden="true" />,
      label: "ERROR",
      style: { color: "#EF5350", borderColor: "rgba(239,83,80,0.3)", backgroundColor: "rgba(239,83,80,0.1)" } as React.CSSProperties,
    },
    pending: {
      icon: <Clock className="h-3 w-3" aria-hidden="true" />,
      label: "PENDING",
      style: { color: "#F59E0B", borderColor: "rgba(245,158,11,0.3)", backgroundColor: "rgba(245,158,11,0.1)" } as React.CSSProperties,
    },
    disconnected: {
      icon: <WifiOff className="h-3 w-3" aria-hidden="true" />,
      label: "DISCONNECTED",
      style: {} as React.CSSProperties, // muted — falls through to default badge styling
    },
  };

  const config = configs[status];

  return (
    <Badge
      variant="outline"
      className="flex items-center gap-1 font-mono text-[10px] tabular-nums"
      style={config.style}
    >
      {config.icon}
      {config.label}
    </Badge>
  );
}

// ── Connection Row ─────────────────────────────────────────────────────────────

/**
 * ConnectionRow — a single brokerage connection with actions
 *
 * WHY separate component (not inline in map): isolates mutation state per
 * connection. If one row's sync is loading, other rows aren't affected.
 * The isPending states from useTriggerBrokerageSync and useDisconnectBrokerageConnection
 * are per-mutation-call, but we still want row-level visual feedback.
 */
interface ConnectionRowProps {
  connection: BrokerageConnection;
}

function ConnectionRow({ connection }: ConnectionRowProps) {
  const { mutate: triggerSync, isPending: syncPending } = useTriggerBrokerageSync();
  const { mutate: disconnect, isPending: disconnectPending } = useDisconnectBrokerageConnection();

  // WHY local syncStatus state: we want to show a transient success message
  // for ~3s after sync is triggered, then revert to normal. The query
  // invalidation in the hook will update last_synced_at when the data refetches.
  const [syncJustTriggered, setSyncJustTriggered] = useState(false);

  function handleSync() {
    triggerSync(connection.connection_id, {
      onSuccess: () => {
        setSyncJustTriggered(true);
        // Reset the transient success message after 3s (same delay as invalidation)
        setTimeout(() => setSyncJustTriggered(false), 3_500);
      },
    });
  }

  // WHY show Sync Now only for active and error:
  //   pending      → OAuth not completed, can't sync yet
  //   disconnected → revoked access, sync would fail
  const canSync = connection.status === "active" || connection.status === "error";

  return (
    <div className="space-y-2">
      {/* WHY px-2 py-1.5: matches Holdings table row density (CompactTable pattern).
          The original px-3 py-2.5 looked out of place next to the tight holdings grid. */}
      <div className="flex flex-wrap items-center gap-3 rounded-md border border-border/50 bg-card px-2 py-1.5">

        {/* ── Brokerage identity ──────────────────────────────────────────── */}
        <div className="min-w-0 flex-1">
          {/* Brokerage name — bold; "Unnamed brokerage" fallback when SnapTrade
              hasn't confirmed the broker yet (pending status) */}
          <p className="truncate text-sm font-medium text-foreground">
            {connection.brokerage_name ?? "Unnamed brokerage"}
          </p>

          {/* Last synced timestamp */}
          <p className="font-mono text-[10px] tabular-nums text-muted-foreground">
            {formatLastSynced(connection.last_synced_at)}
            {/* WHY show brief sync feedback inline: saves vertical space vs a toast */}
            {syncJustTriggered && (
              <span className="ml-2" style={{ color: "#26A69A" }}>
                Sync queued…
              </span>
            )}
          </p>
        </div>

        {/* ── Status badge ───────────────────────────────────────────────── */}
        <StatusBadge status={connection.status} />

        {/* ── Actions ──────────────────────────────────────────────────────── */}
        <div className="flex items-center gap-2">

          {/* Sync Now — only for active/error connections.
              WHY outline with blue tint (not ghost): it's the primary action on an
              active connection row. Ghost blends with the background; the subtle
              blue tint makes it scannable as "the thing to click for data freshness". */}
          {canSync && (
            <Button
              variant="outline"
              size="sm"
              className="h-7 gap-1.5 px-2.5 text-xs"
              // WHY inline style for primary blue: Tailwind's `border-primary` and
              // `text-primary` reference the CSS variable, which correctly resolves
              // to #0EA5E9 without hardcoding the value in className.
              style={{ borderColor: "rgba(14,165,233,0.4)", color: "#0EA5E9" }}
              onClick={handleSync}
              disabled={syncPending}
              title="Trigger an immediate transaction sync"
            >
              {syncPending ? (
                // Loading spinner replaces icon while sync is in flight
                <Loader2 className="h-3 w-3 animate-spin" aria-hidden="true" />
              ) : (
                <RefreshCw className="h-3 w-3" aria-hidden="true" />
              )}
              {syncPending ? "Syncing…" : "Sync Now"}
            </Button>
          )}

          {/* Disconnect — AlertDialog requires confirmation before destructive action */}
          <AlertDialog>
            <AlertDialogTrigger asChild>
              <Button
                variant="ghost"
                size="sm"
                className="h-7 px-2.5 text-xs text-destructive hover:bg-destructive/10 hover:text-destructive"
                disabled={disconnectPending}
                title="Disconnect this brokerage account"
              >
                {disconnectPending ? (
                  <Loader2 className="h-3 w-3 animate-spin" aria-hidden="true" />
                ) : (
                  <Trash2 className="h-3 w-3" aria-hidden="true" />
                )}
              </Button>
            </AlertDialogTrigger>

            {/* Confirmation dialog — prevents accidental disconnection */}
            <AlertDialogContent>
              <AlertDialogHeader>
                <AlertDialogTitle>Disconnect Brokerage</AlertDialogTitle>
                <AlertDialogDescription>
                  This will remove{" "}
                  <strong>{connection.brokerage_name ?? "this brokerage"}</strong>{" "}
                  connection. No existing transactions will be deleted, but future
                  syncs will stop. You can reconnect at any time.
                </AlertDialogDescription>
              </AlertDialogHeader>
              <AlertDialogFooter>
                <AlertDialogCancel>Cancel</AlertDialogCancel>
                <AlertDialogAction
                  onClick={() => disconnect(connection.connection_id)}
                  // WHY red action: this is a destructive operation; the red color
                  // reinforces the severity of the action to avoid accidental clicks.
                  className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
                >
                  Disconnect
                </AlertDialogAction>
              </AlertDialogFooter>
            </AlertDialogContent>
          </AlertDialog>
        </div>
      </div>

      {/* Sync errors banner — rendered beneath the row, only when errors exist */}
      <SyncErrorsBanner connectionId={connection.connection_id} />
    </div>
  );
}

// ── Main component ─────────────────────────────────────────────────────────────

interface ConnectedBrokeragesListProps {
  /** The portfolio whose connections to display */
  portfolioId: string;
}

export function ConnectedBrokeragesList({ portfolioId }: ConnectedBrokeragesListProps) {
  const { data: connections, isLoading, isError } = useBrokerageConnections(portfolioId);

  // ── Loading state — skeleton rows prevent CLS ────────────────────────────
  if (isLoading) {
    return (
      <div className="space-y-2" aria-busy="true" aria-label="Loading brokerage connections">
        {/* WHY 3 skeletons: most users will have 0-2 connections; 3 covers the
            typical case without excessive vertical space on initial paint. */}
        {Array.from({ length: 3 }).map((_, i) => (
          <div
            key={i}
            className="flex items-center gap-3 rounded-md border border-border/50 px-2 py-1.5"
          >
            <div className="flex-1 space-y-1.5">
              <Skeleton className="h-4 w-40" />
              <Skeleton className="h-3 w-24" />
            </div>
            <Skeleton className="h-5 w-20" />
            <Skeleton className="h-7 w-20" />
            <Skeleton className="h-7 w-7" />
          </div>
        ))}
      </div>
    );
  }

  // ── Error state ──────────────────────────────────────────────────────────
  if (isError) {
    return (
      <div className="rounded-md border border-destructive/30 bg-destructive/10 px-4 py-3">
        <div className="flex items-center gap-2">
          <AlertCircle className="h-4 w-4 text-destructive" aria-hidden="true" />
          <p className="text-sm text-destructive">
            Failed to load brokerage connections. Please refresh.
          </p>
        </div>
      </div>
    );
  }

  // ── Empty state ──────────────────────────────────────────────────────────
  if (!connections || connections.length === 0) {
    return (
      // WHY py-6 not py-8: finance UIs are compact; excessive vertical space
      // in an empty state reads as "consumer app", not terminal UI.
      <div className="rounded-md border border-border/50 bg-muted/20 px-4 py-6 text-center">
        {/* WHY Link2 not WifiOff: WifiOff implies a connectivity problem.
            Link2 communicates "link two accounts together" — the correct
            mental model for a first-time brokerage connection. */}
        <Link2 className="mx-auto mb-3 h-8 w-8 text-muted-foreground/50" aria-hidden="true" />
        <p className="text-sm text-muted-foreground">No brokerages connected.</p>
        <p className="mt-1 text-xs text-muted-foreground/70">
          Click &apos;Connect Brokerage&apos; to import your transaction history.
        </p>
      </div>
    );
  }

  // ── Loaded state — one row per connection ────────────────────────────────
  return (
    <div className="space-y-2">
      {connections.map((conn) => (
        <ConnectionRow key={conn.connection_id} connection={conn} />
      ))}
    </div>
  );
}
