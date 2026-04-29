/**
 * components/alerts/AlertHistoryTab.tsx — paginated alert history table.
 *
 * WHY THIS EXISTS (PLAN-0051 Wave D T-D-4-04):
 * The History tab needs server-side filtering (severity, date range, entity,
 * status) plus offset-based pagination. We keep it in its own file so the
 * AlertsList stays focused on the active list and this component owns the
 * filter UI + paged query.
 *
 * BACKEND ENDPOINT: GET /v1/alerts/history (parallel S10 agent owns the
 * implementation; gateway wrapper is `getAlertHistory` in lib/gateway.ts).
 *
 * WHY 30s staleTime (cited in queryFn): alerts arrive every few minutes; a
 * 30-second cache prevents the list from re-fetching on every prop change
 * (e.g. opening / closing the AlertDetailSheet) but still feels live —
 * users will see new alerts within half a minute of the next render.
 */

"use client";
// WHY "use client": uses useState (filters), useQuery (paged data), and
// useDebounce (entity-filter input).

import { useState, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
import { useDebounce } from "@/hooks/useDebounce";
import { Skeleton } from "@/components/ui/skeleton";
import { cn, formatRelativeTime } from "@/lib/utils";
import type { Alert, AlertHistoryParams, AlertSeverity } from "@/types/api";

// ── Constants ──────────────────────────────────────────────────────────────

/**
 * SEVERITY_OPTIONS — render order in the filter pill row.
 * "ALL" is a sentinel for "no filter" (we omit `severity` from the query).
 */
const SEVERITY_OPTIONS: Array<AlertSeverity | "ALL"> = ["ALL", "LOW", "MEDIUM", "HIGH", "CRITICAL"];

/** Page size — default to 50 rows per page; "Load more" appends another 50. */
const PAGE_SIZE = 50;

// ── Hook: useAlertHistory ──────────────────────────────────────────────────

/**
 * useAlertHistory — typed wrapper around the /v1/alerts/history endpoint.
 *
 * WHY 30s staleTime: alerts arrive every few minutes; a 30s cache prevents
 * the table from flickering on every prop change but still feels live.
 *
 * WHY a hook (not inline useQuery): exporting it lets the SnoozedTab and
 * AcknowledgedTab share the exact same caching key + transform layer.
 */
export function useAlertHistory(filters: AlertHistoryParams) {
  const { accessToken } = useAuth();
  return useQuery({
    queryKey: ["alerts-history", filters],
    queryFn: () => createGateway(accessToken).getAlertHistory(filters),
    enabled: Boolean(accessToken),
    staleTime: 30_000,
  });
}

// ── Component ──────────────────────────────────────────────────────────────

interface AlertHistoryTabProps {
  /** Pre-set status filter (e.g. SnoozedTab passes "snoozed"). */
  fixedStatus?: AlertHistoryParams["status"];
}

export function AlertHistoryTab({ fixedStatus }: AlertHistoryTabProps = {}) {
  const router = useRouter();

  // ── Filter state ───────────────────────────────────────────────────────
  const [severity, setSeverity] = useState<AlertSeverity | "ALL">("ALL");
  const [from, setFrom] = useState<string>(""); // YYYY-MM-DD
  const [to, setTo] = useState<string>("");
  const [entitySearch, setEntitySearch] = useState<string>("");
  const debouncedEntity = useDebounce(entitySearch, 300);

  // ── Pagination state ──────────────────────────────────────────────────
  const [pageCount, setPageCount] = useState(1); // # of "Load more" clicks +1

  // ── Derive query params ───────────────────────────────────────────────
  const params = useMemo<AlertHistoryParams>(() => {
    const p: AlertHistoryParams = {
      limit: PAGE_SIZE * pageCount,
      offset: 0,
    };
    if (fixedStatus) p.status = fixedStatus;
    if (severity !== "ALL") p.severity = severity;
    if (from) p.from = new Date(`${from}T00:00:00Z`).toISOString();
    if (to) p.to = new Date(`${to}T23:59:59Z`).toISOString();
    if (debouncedEntity.trim()) p.entity_id = debouncedEntity.trim();
    return p;
  }, [fixedStatus, severity, from, to, debouncedEntity, pageCount]);

  const { data, isLoading, isError, refetch } = useAlertHistory(params);

  const rows = data?.alerts ?? [];
  const total = data?.total ?? 0;
  // Are there more rows on the server we haven't loaded yet?
  // WHY both `has_more` and a row-count fallback: QA-iter1 C-3 — backend
  // ``total`` is now the universe size, so ``rows.length < total`` is
  // correct. We still prefer the server-provided flag when present so any
  // future tweak to pagination semantics doesn't drift between server and
  // client (e.g. cursor-based pagination later).
  const hasMore = data?.has_more ?? rows.length < total;

  // ── Handlers ──────────────────────────────────────────────────────────

  /**
   * handleResetPagination — when filters change we want to reset to page 1.
   * WHY only on filter change (not every state update): pageCount is part
   * of params; we can't reset it inside the same setState pass without
   * losing the filter that triggered the change.
   */
  function handleSeverityChange(next: AlertSeverity | "ALL") {
    setSeverity(next);
    setPageCount(1);
  }

  return (
    <div className="space-y-2">
      {/* ── Filter row ──────────────────────────────────────────────── */}
      <div className="flex flex-wrap items-center gap-2 rounded-[2px] border border-border/40 bg-muted/10 p-2">
        {/* Severity filter pills */}
        <div className="flex gap-1" role="group" aria-label="Filter by severity">
          {SEVERITY_OPTIONS.map((opt) => (
            <button
              key={opt}
              type="button"
              onClick={() => handleSeverityChange(opt)}
              className={cn(
                "rounded-[2px] border px-2 py-0.5 text-[10px] uppercase tracking-[0.08em]",
                severity === opt
                  ? "border-primary bg-primary/15 text-foreground"
                  : "border-border/40 bg-muted/20 text-muted-foreground hover:bg-muted/40 hover:text-foreground",
              )}
              aria-pressed={severity === opt}
            >
              {opt}
            </button>
          ))}
        </div>

        {/* Date range — uses native date inputs (cheaper than a 3rd-party calendar) */}
        <label className="flex items-center gap-1 text-[10px] text-muted-foreground">
          From
          <input
            type="date"
            value={from}
            onChange={(e) => {
              setFrom(e.target.value);
              setPageCount(1);
            }}
            className="h-6 rounded-[2px] border border-border bg-background px-1 text-[11px] text-foreground"
            aria-label="From date"
          />
        </label>
        <label className="flex items-center gap-1 text-[10px] text-muted-foreground">
          To
          <input
            type="date"
            value={to}
            onChange={(e) => {
              setTo(e.target.value);
              setPageCount(1);
            }}
            className="h-6 rounded-[2px] border border-border bg-background px-1 text-[11px] text-foreground"
            aria-label="To date"
          />
        </label>

        {/* Entity filter (free-text — backend matches by entity_id) */}
        <input
          type="text"
          value={entitySearch}
          onChange={(e) => {
            setEntitySearch(e.target.value);
            setPageCount(1);
          }}
          placeholder="Entity id…"
          className="h-6 rounded-[2px] border border-border bg-background px-2 text-[11px] text-foreground placeholder:text-muted-foreground"
          aria-label="Entity filter"
        />
      </div>

      {/* ── Result table ──────────────────────────────────────────────── */}
      {isLoading ? (
        <div className="space-y-1" aria-busy="true" aria-label="Loading alert history">
          {Array.from({ length: 6 }).map((_, i) => (
            <Skeleton key={i} className="h-6 w-full" />
          ))}
        </div>
      ) : isError ? (
        <div className="rounded-[2px] border border-destructive/30 bg-destructive/10 p-3 text-[11px] text-destructive">
          Failed to load alert history.
          <button
            type="button"
            onClick={() => void refetch()}
            className="ml-2 underline-offset-2 hover:underline"
          >
            Retry
          </button>
        </div>
      ) : rows.length === 0 ? (
        <p className="py-6 text-center text-[11px] text-muted-foreground">
          No alerts match the current filters.
        </p>
      ) : (
        <>
          {/* WHY a real <table>: history is tabular data; semantic HTML
              helps screen-readers + lets us reuse browser table styling. */}
          <table className="w-full border-collapse text-[11px]">
            <thead className="border-b border-border/60 text-[9px] uppercase tracking-[0.08em] text-muted-foreground">
              <tr>
                <th className="px-2 py-1 text-left">Severity</th>
                <th className="px-2 py-1 text-left">Ticker</th>
                <th className="px-2 py-1 text-left">Type</th>
                <th className="px-2 py-1 text-left">Fired</th>
                <th className="px-2 py-1 text-left">Dismissed</th>
                <th className="px-2 py-1 text-left">Status</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <HistoryRow key={row.alert_id} alert={row} onSelect={() => router.replace(`/alerts?selected=${encodeURIComponent(row.alert_id)}`)} />
              ))}
            </tbody>
          </table>

          {/* Load-more button */}
          {hasMore && (
            <div className="flex justify-center pt-2">
              <button
                type="button"
                onClick={() => setPageCount((p) => p + 1)}
                className="rounded-[2px] border border-border/40 bg-muted/20 px-3 py-1 text-[11px] text-muted-foreground hover:bg-muted/40 hover:text-foreground"
              >
                Load more ({total - rows.length} remaining)
              </button>
            </div>
          )}
        </>
      )}
    </div>
  );
}

// ── HistoryRow ─────────────────────────────────────────────────────────────

/**
 * HistoryRow — one row of the history table.
 *
 * WHY a sub-component: keeps the JSX in the parent terse + lets us isolate
 * the formatting logic (relative+absolute time, status badge color) here.
 */
function HistoryRow({ alert, onSelect }: { alert: Alert; onSelect: () => void }) {
  // Determine status: acked > snoozed > active. (Backend may return these
  // explicitly but we infer to be defensive against missing fields.)
  const sevKey = ((alert.severity ?? "").toUpperCase() || "LOW") as AlertSeverity;
  const status = computeStatus(alert);
  const statusClass = STATUS_PILL_CLASS[status];

  return (
    <tr className="border-b border-border/30 hover:bg-muted/30">
      <td className="px-2 py-1">
        <span
          className={cn(
            "inline-block rounded-[2px] px-1 text-[9px] uppercase tracking-[0.08em]",
            SEVERITY_PILL_CLASS[sevKey],
          )}
        >
          {sevKey}
        </span>
      </td>
      <td className="px-2 py-1 font-mono tabular-nums">{alert.ticker ?? "—"}</td>
      <td className="px-2 py-1">
        <button
          type="button"
          onClick={onSelect}
          className="text-foreground underline-offset-2 hover:underline"
        >
          {alert.alert_type}
        </button>
      </td>
      <td className="px-2 py-1 text-muted-foreground" title={alert.created_at}>
        <span className="font-mono tabular-nums">{formatRelativeTime(alert.created_at)}</span>
      </td>
      <td className="px-2 py-1 text-muted-foreground" title={alert.acknowledged_at ?? ""}>
        {alert.acknowledged_at ? (
          <span className="font-mono tabular-nums">{formatRelativeTime(alert.acknowledged_at)}</span>
        ) : (
          "—"
        )}
      </td>
      <td className="px-2 py-1">
        <span className={cn("rounded-[2px] px-1 text-[9px] uppercase tracking-[0.08em]", statusClass)}>
          {status}
        </span>
      </td>
    </tr>
  );
}

// ── Helpers ────────────────────────────────────────────────────────────────

function computeStatus(alert: Alert): "active" | "ack" | "snoozed" {
  if (alert.acknowledged_at) return "ack";
  const snoozeUntil = alert.snooze_until ? new Date(alert.snooze_until).getTime() : 0;
  if (snoozeUntil && snoozeUntil > Date.now()) return "snoozed";
  return "active";
}

const SEVERITY_PILL_CLASS: Record<AlertSeverity, string> = {
  CRITICAL: "bg-negative/20 text-negative",
  HIGH: "bg-warning/20 text-warning",
  MEDIUM: "bg-primary/15 text-primary",
  LOW: "bg-muted/40 text-muted-foreground",
};

const STATUS_PILL_CLASS: Record<"active" | "ack" | "snoozed", string> = {
  active: "bg-primary/15 text-primary",
  ack: "bg-muted/40 text-muted-foreground",
  snoozed: "bg-warning/20 text-warning",
};
