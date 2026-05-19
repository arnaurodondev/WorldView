/**
 * components/alerts/AlertHistoryTab.tsx — alert history table with infinite scroll.
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
 * WHY useInfiniteQuery (MED-021):
 * Alert history can grow to thousands of rows. The previous useQuery approach
 * expanded `limit` by PAGE_SIZE on each "Load more" click — this re-fetched
 * the entire dataset from offset=0 every time (wasteful). useInfiniteQuery
 * fetches only the next PAGE_SIZE rows by passing the correct offset, then
 * concatenates pages in memory. The IntersectionObserver at the list bottom
 * auto-triggers the next page when the user scrolls there, eliminating the
 * manual "Load more" button click.
 *
 * WHY 30s staleTime: alerts arrive every few minutes; a 30s cache prevents
 * the table from flickering on every prop change but still feels live.
 */

"use client";
// WHY "use client": uses useState (filters), useInfiniteQuery (paged data),
// useDebounce (entity-filter input), and useEffect (IntersectionObserver).

import { useState, useMemo, useEffect, useRef } from "react";
import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
import { useDebounce } from "@/hooks/useDebounce";
import { cn } from "@/lib/utils";
import { DataTable } from "@/components/ui/data-table";
import { alertHistoryColumns } from "./alert-history-columns";
import type { AlertHistoryParams, AlertSeverity, AlertsResponse } from "@/types/api";

// ── Constants ──────────────────────────────────────────────────────────────

/**
 * SEVERITY_OPTIONS — render order in the filter pill row.
 * "ALL" is a sentinel for "no filter" (we omit `severity` from the query).
 */
const SEVERITY_OPTIONS: Array<AlertSeverity | "ALL"> = ["ALL", "LOW", "MEDIUM", "HIGH", "CRITICAL"];

/**
 * PAGE_SIZE — rows fetched per page.
 * WHY 50: gives enough context for pattern scanning without over-fetching.
 * The IntersectionObserver triggers the next page when the sentinel div
 * at the bottom of the list enters the viewport.
 */
const PAGE_SIZE = 50;

// ── Hook: useAlertHistoryInfinite ──────────────────────────────────────────

/**
 * useAlertHistoryInfinite — offset-based infinite query for alert history.
 *
 * WHY useInfiniteQuery (not useQuery + expanding limit):
 * The previous approach sent `limit = PAGE_SIZE * pageCount` on each "Load
 * more" click, which re-fetched all previously seen rows every time the user
 * wanted more. useInfiniteQuery keeps each PAGE_SIZE slice in its own cache
 * entry and only fetches the delta (next 50 rows) on scroll.
 *
 * WHY offset as pageParam:
 * The /v1/alerts/history endpoint uses standard offset+limit pagination (not
 * a cursor). `pageParam` starts at 0; getNextPageParam increments by PAGE_SIZE
 * until the last page returns fewer than PAGE_SIZE rows, signalling exhaustion.
 */
export function useAlertHistoryInfinite(baseFilters: Omit<AlertHistoryParams, "limit" | "offset">) {
  const { accessToken } = useAuth();
  return useInfiniteQuery<AlertsResponse>({
    // WHY include baseFilters in key: filter changes bust the cache so we start
    // fetching from page 1 again rather than showing stale filtered pages.
    queryKey: ["alerts-history-infinite", baseFilters],
    queryFn: ({ pageParam }: { pageParam: number }) => {
      const filters: AlertHistoryParams = {
        ...baseFilters,
        limit: PAGE_SIZE,
        // WHY use pageParam directly (not cast): initialPageParam is typed as
        // `number`, so TanStack infers pageParam as `number` here. No cast needed.
        offset: pageParam,
      };
      return createGateway(accessToken).getAlertHistory(filters);
    },
    // WHY 0 as initialPageParam: offset starts at the first row.
    initialPageParam: 0,
    getNextPageParam: (lastPage: AlertsResponse, allPages: AlertsResponse[]) => {
      // WHY prefer has_more: the server signals exhaustion explicitly.
      // Fallback: if the last page returned a full PAGE_SIZE we assume there
      // are more rows; once it returns fewer we stop.
      const serverSaysMore = lastPage.has_more ?? (lastPage.alerts.length === PAGE_SIZE);
      return serverSaysMore ? allPages.length * PAGE_SIZE : undefined;
    },
    enabled: Boolean(accessToken),
    staleTime: 30_000,
  });
}

/**
 * useAlertHistory — legacy typed wrapper kept for backward compatibility.
 * New code should use useAlertHistoryInfinite instead.
 *
 * WHY keep this: RuleManagerDialog and other consumers import this hook by
 * name. Removing it would break those callers before they migrate. It can be
 * deleted once all call sites have migrated to useAlertHistoryInfinite.
 *
 * @deprecated Use useAlertHistoryInfinite for new consumers.
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

  // ── Derive base filter params (without pagination) ────────────────────
  // WHY omit limit/offset: useAlertHistoryInfinite injects its own pagination
  // params per page. Including them here would create a stale params object
  // that overrides the per-page offset inside the queryFn.
  const baseFilters = useMemo<Omit<AlertHistoryParams, "limit" | "offset">>(() => {
    const p: Omit<AlertHistoryParams, "limit" | "offset"> = {};
    if (fixedStatus) p.status = fixedStatus;
    if (severity !== "ALL") p.severity = severity;
    if (from) p.from = new Date(`${from}T00:00:00Z`).toISOString();
    if (to) p.to = new Date(`${to}T23:59:59Z`).toISOString();
    if (debouncedEntity.trim()) p.entity_id = debouncedEntity.trim();
    return p;
  }, [fixedStatus, severity, from, to, debouncedEntity]);

  // ── Infinite query ────────────────────────────────────────────────────
  // WHY useAlertHistoryInfinite (not useQuery + expanding limit):
  // See the hook JSDoc above. Short version: this only fetches the delta
  // (next 50 rows) on scroll rather than re-fetching all previously seen rows.
  const {
    data,
    isLoading,
    isError,
    refetch,
    fetchNextPage,
    hasNextPage,
    isFetchingNextPage,
  } = useAlertHistoryInfinite(baseFilters);

  // Flatten all pages into a single array for the DataTable.
  // WHY flatMap (not concat/reduce): flatMap is the idiomatic TanStack pattern
  // for infinite queries and handles the empty initial state (undefined data)
  // cleanly via the `?? []` fallback.
  const rows = useMemo(
    () => data?.pages.flatMap((p: AlertsResponse) => p.alerts) ?? [],
    [data],
  );

  // ── IntersectionObserver — auto-fetch next page on scroll ─────────────
  // WHY IntersectionObserver (not a "Load more" button):
  // MED-021 requirement. The sentinel div at the bottom of the list enters
  // the viewport once the user scrolls past the last visible row. At that
  // point we call fetchNextPage() so the next 50 rows load automatically.
  // threshold:0.5 means the sentinel must be at least half-visible before
  // the callback fires — avoids a spurious fetch when the list is very short
  // and the sentinel is visible on initial render.
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const sentinel = bottomRef.current;
    if (!sentinel) return;

    const observer = new IntersectionObserver(
      ([entry]) => {
        // WHY guard on !isFetchingNextPage: prevents duplicate parallel fetches
        // if the sentinel stays in view while a fetch is in progress.
        if (entry.isIntersecting && hasNextPage && !isFetchingNextPage) {
          void fetchNextPage();
        }
      },
      { threshold: 0.5 },
    );

    observer.observe(sentinel);
    // WHY disconnect in cleanup: prevents the observer from firing after the
    // component unmounts (e.g. when the user switches to the Active tab) which
    // would call fetchNextPage on a now-stale query.
    return () => observer.disconnect();
  }, [hasNextPage, isFetchingNextPage, fetchNextPage]);

  // ── Handlers ──────────────────────────────────────────────────────────

  /**
   * handleSeverityChange — severity filter also resets to page 1.
   * WHY: when filters change the query key changes, causing useInfiniteQuery
   * to automatically reset its page cursor to page 0. We don't need to
   * manually track pageCount anymore — filter state change is the trigger.
   */
  function handleSeverityChange(next: AlertSeverity | "ALL") {
    setSeverity(next);
  }

  return (
    <div className="space-y-1">
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
            onChange={(e) => setFrom(e.target.value)}
            className="h-6 rounded-[2px] border border-border bg-background px-1 text-[11px] text-foreground"
            aria-label="From date"
          />
        </label>
        <label className="flex items-center gap-1 text-[10px] text-muted-foreground">
          To
          <input
            type="date"
            value={to}
            onChange={(e) => setTo(e.target.value)}
            className="h-6 rounded-[2px] border border-border bg-background px-1 text-[11px] text-foreground"
            aria-label="To date"
          />
        </label>

        {/* Entity filter (free-text — backend matches by entity_id) */}
        <input
          type="text"
          value={entitySearch}
          onChange={(e) => setEntitySearch(e.target.value)}
          placeholder="Entity id…"
          className="h-6 rounded-[2px] border border-border bg-background px-2 text-[11px] text-foreground placeholder:text-muted-foreground"
          aria-label="Entity filter"
        />
      </div>

      {/* ── Result table ──────────────────────────────────────────────── */}
      {isError ? (
        // Error shown outside DataTable so the table chrome doesn't render
        // in a broken state. Retry lets the user re-issue the query.
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
      ) : (
        <>
          {/*
           * WHY DataTable (not raw <table>): provides uniform density, multi-column
           * sort, copy-as-TSV, sticky header, and column resize for free.
           * The alertHistoryColumns definition lives in alert-history-columns.tsx
           * so it can be unit-tested independently.
           */}
          <DataTable
            columns={alertHistoryColumns}
            data={rows}
            getRowId={(a) => a.alert_id}
            density="compact"
            isLoading={isLoading}
            emptyMessage="No alerts match the current filters."
            onRowClick={(alert) =>
              router.replace(`/alerts?selected=${encodeURIComponent(alert.alert_id)}`)
            }
          />

          {/* ── Infinite scroll sentinel ─────────────────────────────── */}
          {/* WHY h-px (not h-0): a zero-height element may not be detected by
              IntersectionObserver in all browsers. 1px guarantees it has a
              measurable bounding rect even when adjacent content is empty. */}
          <div ref={bottomRef} className="h-px" aria-hidden="true" />

          {/* Loading indicator for subsequent pages (not the initial skeleton) */}
          {isFetchingNextPage && (
            <div className="flex justify-center py-2">
              <span className="text-[11px] text-muted-foreground">Loading more…</span>
            </div>
          )}

          {/* End-of-list message — only shown after all pages are loaded */}
          {!hasNextPage && rows.length > 0 && !isLoading && (
            <div className="flex justify-center py-2">
              <span className="text-[10px] text-muted-foreground/60">
                All {rows.length} alert{rows.length === 1 ? "" : "s"} loaded
              </span>
            </div>
          )}
        </>
      )}
    </div>
  );
}

// HistoryRow sub-component and its helpers (computeStatus, SEVERITY_PILL_CLASS,
// STATUS_PILL_CLASS) have moved to alert-history-columns.tsx for isolated testing.
