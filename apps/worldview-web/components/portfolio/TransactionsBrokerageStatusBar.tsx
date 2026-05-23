/**
 * components/portfolio/TransactionsBrokerageStatusBar.tsx — Collapsible 22px
 * brokerage sync status bar for the Transactions tab (PRD-0089 SA-C Task 6).
 *
 * WHY THIS EXISTS: Traders want to know at a glance whether their brokerage is
 * connected and when it last synced. A full brokerage management panel
 * (ConnectedBrokeragesList) is already available in the tab, but it requires
 * clicking to expand. This bar gives a persistent, compact health indicator at
 * the very top of the tab so the user can immediately spot connection issues
 * without scrolling or expanding panels.
 *
 * WHY COLLAPSIBLE: The bar is informational — if all is green, most users
 * won't need to see the details. Collapsed by default keeps the transaction
 * table immediately visible (the primary use case). A single click reveals
 * the connection list for troubleshooting.
 *
 * STATUS DOT COLOURS (design tokens, never raw hex):
 *   green  → text-positive  (all connections healthy)
 *   yellow → text-warning   (syncing / pending)
 *   red    → text-negative  (at least one error)
 *   gray   → text-muted-foreground (no connections yet)
 *
 * WHO USES IT: features/portfolio/components/TransactionsTab.tsx
 * DATA SOURCE: createGateway().getBrokerageConnections(portfolioId) via useQuery
 * DESIGN REFERENCE: PRD-0022 §6.6; PRD-0089 SA-C
 */

"use client";
// WHY "use client": uses useState (collapse state), useQuery (data fetch),
// and event handlers — all browser-only React primitives.

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ChevronRight } from "lucide-react";

import { cn } from "@/lib/utils";
import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
import { qk } from "@/lib/query/keys";
import type { BrokerageConnection } from "@/types/api";

// ── Props ──────────────────────────────────────────────────────────────────────

interface TransactionsBrokerageStatusBarProps {
  /**
   * The portfolio whose brokerage connections to show.
   * When null/undefined, the query is disabled and the bar shows "Not connected".
   */
  portfolioId: string | null | undefined;
}

// ── Helpers ────────────────────────────────────────────────────────────────────

/**
 * deriveStatus — compute aggregate status from a list of connections.
 *
 * WHY this order (error > syncing > active): if ANY connection has an error,
 * the user should see red immediately — an active connection elsewhere doesn't
 * hide the broken one. Syncing comes before active so a background sync is
 * surfaced even when other connections are idle.
 */
function deriveStatus(
  connections: BrokerageConnection[],
): "connected" | "syncing" | "error" | "none" {
  if (connections.length === 0) return "none";
  if (connections.some((c) => c.status === "error")) return "error";
  // WHY pending maps to syncing: "pending" means OAuth initiated but not yet
  // confirmed — visually it's the same "in progress" state as a sync in flight.
  if (connections.some((c) => c.status === "pending")) return "syncing";
  // All remaining active/disconnected — active = healthy.
  if (connections.every((c) => c.status === "active")) return "connected";
  return "connected";
}

/**
 * statusDotClass — returns the Tailwind text-colour class for the status dot.
 *
 * WHY design tokens (not raw colours): the dark-mode palette is defined via CSS
 * variables in globals.css. Using token classes (text-positive, text-warning,
 * text-negative, text-muted-foreground) automatically adapts to any future
 * theme changes without touching this file.
 */
function statusDotClass(status: ReturnType<typeof deriveStatus>): string {
  switch (status) {
    case "connected":
      return "text-positive";
    case "syncing":
      // WHY text-warning: yellow / amber signals "in progress" — not broken,
      // but not yet settled. Matches the warning token used in AlertSeverity
      // MEDIUM badges elsewhere in the app.
      return "text-warning";
    case "error":
      return "text-negative";
    case "none":
    default:
      return "text-muted-foreground";
  }
}

/**
 * statusLabel — human-readable status line for the collapsed bar.
 */
function statusLabel(
  status: ReturnType<typeof deriveStatus>,
  count: number,
): string {
  switch (status) {
    case "connected":
      return count === 1
        ? "Brokerage: Connected"
        : `Brokerage: ${count} connected`;
    case "syncing":
      return "Brokerage: Syncing…";
    case "error":
      return "Brokerage: Connection error";
    case "none":
      return "Brokerage: Not connected";
  }
}

// ── Component ─────────────────────────────────────────────────────────────────

export function TransactionsBrokerageStatusBar({
  portfolioId,
}: TransactionsBrokerageStatusBarProps) {
  // WHY false by default: the bar is a secondary indicator. Start collapsed so
  // the transactions table is immediately visible — the primary use case.
  const [expanded, setExpanded] = useState(false);

  // Auth — needed to create the gateway and as part of the query enabled guard.
  const { accessToken } = useAuth();

  // ── Query: brokerage connections for this portfolio ───────────────────
  //
  // WHY qk.brokerage.connections() key: the brokerage.* namespace is designed
  // for connection-management queries (vs. brokerageStatus which is a per-user
  // health-check badge). Since this bar renders per-portfolio connection detail
  // we use the connections key so cache invalidation from ConnectedBrokeragesList
  // mutations (sync, disconnect) also refreshes this bar automatically.
  //
  // WHY 60s refetchInterval: brokerage status changes asynchronously (the worker
  // processes syncs in the background). 60s polling gives near-realtime feedback
  // without hammering S9.
  const { data: connections, isLoading } = useQuery<BrokerageConnection[]>({
    queryKey: [...qk.brokerage.connections(), portfolioId ?? ""] as const,
    queryFn: () =>
      createGateway(accessToken).getBrokerageConnections(portfolioId ?? undefined),
    enabled: !!accessToken && !!portfolioId,
    staleTime: 30_000,
    refetchInterval: 60_000,
  });

  // ── Derived state ─────────────────────────────────────────────────────
  const connectionList = connections ?? [];
  const status = deriveStatus(connectionList);
  const dotClass = statusDotClass(status);
  const label = statusLabel(status, connectionList.length);

  // ── Render ────────────────────────────────────────────────────────────
  return (
    <div
      data-testid="brokerage-status-bar"
      // WHY border-b: visually separates the status bar from the filter bar
      // and transactions table below it.
      className="shrink-0 border-b border-border bg-card"
    >
      {/* ── Collapsed header — always visible ──────────────────── */}
      <button
        type="button"
        aria-expanded={expanded}
        aria-label={`${label}. Click to ${expanded ? "collapse" : "expand"} brokerage details`}
        onClick={() => setExpanded((v) => !v)}
        // WHY h-[22px]: the task spec calls for a 22px collapsed bar.
        // h-[22px] is a non-standard Tailwind arbitrary value that produces
        // exactly 22px — enough for an 11px label + 4px top/bottom padding.
        className="flex h-[22px] w-full items-center gap-1.5 px-2 text-left hover:bg-muted/30 transition-colors"
      >
        {/* Chevron rotates 90° when expanded */}
        <ChevronRight
          className={cn(
            "h-3 w-3 shrink-0 text-muted-foreground transition-[transform] duration-150",
            expanded && "rotate-90",
          )}
        />

        {/* Status dot — filled circle rendered as a Unicode bullet styled
            with the status colour token. Using a span rather than an SVG
            keeps the DOM minimal and avoids an extra icon import. */}
        {isLoading ? (
          // WHY animate-pulse: indicates a loading state without a spinner
          // that would be oversized in a 22px bar.
          <span
            className="h-2 w-2 rounded-full bg-muted-foreground/40 animate-pulse"
            aria-hidden
          />
        ) : (
          <span
            data-testid="brokerage-status-dot"
            aria-hidden
            // WHY inline-block with fill: the dot is a purely decorative indicator.
            // Sizing to 8×8px (h-2 w-2) keeps it subtle inside the 22px bar.
            className={cn(
              "h-2 w-2 rounded-full shrink-0",
              // Map the status to a background colour (not text-colour, since
              // it's a filled dot — bg- prefix on the same token value).
              status === "connected" && "bg-positive",
              status === "syncing" && "bg-warning",
              status === "error" && "bg-negative",
              status === "none" && "bg-muted-foreground/50",
            )}
          />
        )}

        {/* Status label text */}
        <span
          className={cn(
            "text-[10px] font-mono uppercase tracking-[0.06em]",
            dotClass,
          )}
        >
          {isLoading ? "Brokerage: Loading…" : label}
        </span>

        {/* Connection count badge — shown only when > 0 connections */}
        {!isLoading && connectionList.length > 0 && (
          <span className="ml-auto text-[10px] font-mono text-muted-foreground tabular-nums">
            {connectionList.length}{" "}
            {connectionList.length === 1 ? "connection" : "connections"}
          </span>
        )}
      </button>

      {/* ── Expanded panel — shows one row per connection ──────── */}
      {/* WHY conditional render (not CSS display:none): avoids running
          the list-rendering code when the user never expands the bar.
          The query already ran — this is purely about DOM nodes. */}
      {expanded && (
        <div
          data-testid="brokerage-status-expanded"
          className="px-2 pb-2 pt-1 space-y-1"
        >
          {connectionList.length === 0 ? (
            <p className="text-[10px] text-muted-foreground font-mono">
              No brokerage connections for this portfolio. Use &ldquo;+ Connect&rdquo; to link a broker.
            </p>
          ) : (
            connectionList.map((conn) => (
              <ConnectionRow key={conn.connection_id} connection={conn} />
            ))
          )}
        </div>
      )}
    </div>
  );
}

// ── ConnectionRow — single row in the expanded panel ─────────────────────────

/**
 * ConnectionRow — renders one brokerage connection in the expanded detail list.
 *
 * WHY a separate subcomponent: keeps the main component clean and makes
 * connection-row rendering independently testable.
 */
function ConnectionRow({ connection }: { connection: BrokerageConnection }) {
  const statusColor =
    connection.status === "active"
      ? "text-positive"
      : connection.status === "error"
        ? "text-negative"
        : connection.status === "pending"
          ? "text-warning"
          : "text-muted-foreground"; // disconnected

  return (
    <div
      data-testid={`brokerage-connection-${connection.connection_id}`}
      className="flex items-center gap-2 text-[10px] font-mono"
    >
      {/* Broker name */}
      <span className="text-foreground font-medium min-w-[80px]">
        {connection.brokerage_name ?? "Unknown broker"}
      </span>

      {/* Status chip */}
      <span className={cn("uppercase tracking-[0.04em]", statusColor)}>
        {connection.status ?? "unknown"}
      </span>

      {/* Last synced timestamp */}
      {connection.last_synced_at && (
        <span className="text-muted-foreground ml-auto">
          synced {new Date(connection.last_synced_at).toLocaleDateString()}
        </span>
      )}
    </div>
  );
}
