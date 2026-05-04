/**
 * components/dashboard/EarningsCalendarWidget.tsx — Upcoming earnings live widget
 *
 * WHY THIS EXISTS: Earnings calendars are a critical part of the morning routine —
 * traders need to know which companies report today or this week to anticipate
 * volatility. This widget fetches live data from S9 /v1/fundamentals/earnings-calendar
 * which proxies to S7's temporal-events endpoint filtered to event_type=corporate.
 *
 * WHY live (not static): PLAN-0068 Wave B-1 completes the earnings data pipeline —
 * intelligence-migrations 0018 adds the 'corporate' event_type, consumer 13D-9
 * populates the table from Finnhub, and S9 exposes the proxy. This component
 * activates the full path.
 *
 * WHO USES IT: app/(app)/dashboard/page.tsx (Row 4, col-span-3)
 * DATA SOURCE: S9 GET /v1/fundamentals/earnings-calendar (PLAN-0068 Wave A-2)
 * DESIGN REFERENCE: PRD-0031 §10 Dashboard Wave 7
 */

"use client";
// WHY "use client": this component uses useQuery (TanStack Query hook) which
// requires client-side rendering. Next.js App Router runs Server Components
// by default — "use client" opts this subtree into the React client bundle.

import { useQuery } from "@tanstack/react-query";
import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
import { Skeleton } from "@/components/ui/skeleton";
import { AlertTriangle } from "lucide-react";
import { Button } from "@/components/ui/button";
import type { EarningsEvent } from "@/types/api";

// ── Component ─────────────────────────────────────────────────────────────────

/**
 * EarningsCalendarWidget — live upcoming earnings events.
 *
 * Renders up to 8 earnings rows in 22px terminal-density rows, matching the
 * EconomicCalendar sister widget. Each row shows:
 *   [date] [time] [ticker] [company name] [EPS estimate]
 */
export function EarningsCalendarWidget() {
  const { accessToken } = useAuth();

  const { data, isLoading, isError, refetch } = useQuery({
    // WHY "earnings-calendar" queryKey: TanStack Query uses this to cache and
    // deduplicate fetches across components. Using the same key as the route
    // name keeps it easy to invalidate when real-time earnings data arrives.
    queryKey: ["earnings-calendar"],
    queryFn: () => createGateway(accessToken).getEarningsCalendar(),
    // WHY enabled guard: if the user is not authenticated yet, accessToken is
    // undefined. We must not fire the request — S9 would return 401 which
    // counts as an error state and would show the error banner on first render.
    enabled: !!accessToken,
    // WHY 10min staleTime: earnings dates are announced weeks in advance and
    // only change when companies pre-announce. 10-minute cache is safe and
    // matches EconomicCalendar's staleness budget.
    staleTime: 10 * 60_000,
    refetchInterval: 10 * 60_000,
  });

  // WHY ?? []: TanStack Query `data` is undefined while loading/error.
  // Defaulting to [] ensures the empty-state branch renders cleanly.
  const events = data?.events ?? [];

  // WHY single outer wrapper for all render paths:
  // All states (loading, error, empty, data) live inside the same bg-background
  // h-full flex-col shell so the panel cell is consistently filled regardless
  // of data state — no "pop" from transparent empty state to filled data state.
  return (
    // WHY bg-background + h-full flex-col: consistent with EconomicCalendar —
    // all Row-4 dashboard panels use this outer container pattern so the gap-px
    // hairline separators look uniform.
    <div className="flex h-full flex-col bg-background">

      {/* ── Section header §0.9 pattern ──────────────────────────────────── */}
      {/* WHY uppercase tracking: terminal-style section label per DESIGN_SYSTEM.md §0.9 */}
      <div className="flex h-6 shrink-0 items-center border-b border-border px-2">
        <span className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground">
          EARNINGS CALENDAR
        </span>
      </div>

      {/* ── Loading state ──────────────────────────────────────────────── */}
      {/* WHY 4 skeleton rows: matches the visible row count when data is present.
          animationDelay staggers the pulse so it doesn't look like a single block. */}
      {isLoading && (
        <div className="flex-1 space-y-2 px-3 py-2">
          {Array.from({ length: 4 }).map((_, i) => (
            // WHY key={i}: index-keyed skeleton rows are safe — they have no
            // identity beyond "placeholder slot N" and never reorder.
            <div key={i} className="flex gap-2">
              <Skeleton className="h-5 w-10" style={{ animationDelay: `${i * 50}ms` }} />
              <Skeleton className="h-5 w-10" style={{ animationDelay: `${i * 50}ms` }} />
              <Skeleton className="h-5 flex-1" style={{ animationDelay: `${i * 50}ms` }} />
              <Skeleton className="h-5 w-16" style={{ animationDelay: `${i * 50}ms` }} />
            </div>
          ))}
        </div>
      )}

      {/* ── Error state ─────────────────────────────────────────────────── */}
      {/* WHY min-h-[88px]: 4 rows × 22px = 88px; preserves widget height so the
          dashboard grid doesn't reflow when the error state appears. */}
      {isError && (
        <div className="flex flex-1 min-h-[88px] items-center justify-center gap-2">
          <AlertTriangle className="h-3 w-3 text-destructive" strokeWidth={1.5} />
          <span className="text-xs text-muted-foreground">Earnings data unavailable</span>
          <Button variant="ghost" size="sm" className="h-6 px-2 text-xs" onClick={() => void refetch()}>
            Retry
          </Button>
        </div>
      )}

      {/* ── Empty state ─────────────────────────────────────────────────── */}
      {/* WHY two-line message: first line tells what is missing; second line tells
          WHY it is missing (no earnings in the default 7-day window). This avoids
          confusion where traders might think the widget is broken. */}
      {!isLoading && !isError && events.length === 0 && (
        // WHY px-3 py-2: T-F-6-03 standardised inner content padding
        <div className="flex flex-1 flex-col gap-0.5 px-3 py-2">
          {/* WHY text-[10px]: terminal labels/metadata use 10px density — text-xs (12px) is consumer app scale (Bloomberg convention) */}
          <p className="text-[10px] text-muted-foreground">No upcoming earnings events scheduled.</p>
          <p className="text-[10px] text-muted-foreground/60">
            Earnings calendar data populates as company reporting schedules are ingested.
          </p>
        </div>
      )}

      {/* ── Event rows ──────────────────────────────────────────────────── */}
      {!isLoading && !isError && events.length > 0 && (
        // WHY divide-y: hairline separators between rows without explicit border classes
        // on each row — same pattern as EconomicCalendar.
        <div className="flex-1 divide-y divide-border/30 overflow-auto">
          {events.slice(0, 8).map((event) => (
            <EarningsRow key={event.event_id} event={event} />
          ))}
        </div>
      )}

    </div>
  );
}

// ── Sub-components ─────────────────────────────────────────────────────────────

/**
 * EarningsRow — single earnings event row at terminal density (22px).
 *
 * Layout: [date] [time] [ticker] [title truncated] [eps snippet from description]
 *
 * WHY extract to sub-component: keeps EarningsCalendarWidget readable and
 * makes the EarningsRow unit-testable independently.
 */
function EarningsRow({ event }: { event: EarningsEvent }) {
  const date = new Date(event.active_from);
  // WHY slice(5,10): extract "MM-DD" from ISO string — avoids locale-dependent
  // toLocaleDateString() which varies by browser timezone settings.
  const dateStr = date.toISOString().slice(5, 10); // "MM-DD"
  const timeStr = date.toISOString().slice(11, 16); // "HH:MM"

  // WHY extract ticker from region: the earnings consumer sets region=ticker
  // for corporate events (LocalEventScope). We display it as the company tag.
  const ticker = event.region;

  // WHY truncate at 40 chars: EarningsCalendarDatasetConsumer (13D-9) builds
  // descriptions in the form "EPS est. $1.45 (BMO)" — short enough to display
  // in full in most cases. We cap at 40 chars to prevent overflow in the
  // narrow column; the full text is available in the title attribute on hover.
  const epsSnippet = event.description.length > 40
    ? `${event.description.slice(0, 37)}…`
    : event.description;

  return (
    <div
      // WHY h-[22px]: terminal row height per §0 Terminal CLI Quality Standard
      className="flex h-[22px] items-center gap-2 px-2 py-0 hover:bg-muted/40"
    >
      {/* Date + time — monospace for column alignment */}
      <div className="shrink-0">
        <span className="font-mono text-[10px] tabular-nums text-muted-foreground">
          {dateStr}
        </span>
        <span className="ml-1 font-mono text-[10px] tabular-nums text-muted-foreground">
          {timeStr}
        </span>
      </div>

      {/* Ticker badge — primary identifier for traders */}
      {/* WHY w-12 shrink-0: fixed width keeps the title column aligned across rows */}
      <span className="w-12 shrink-0 font-mono text-[11px] font-semibold text-foreground">
        {ticker}
      </span>

      {/* Event title — company name + quarter, truncated when long */}
      <p
        className="min-w-0 flex-1 truncate text-[11px] text-foreground"
        title={event.title}
      >
        {event.title}
      </p>

      {/* EPS snippet — contextual detail from description */}
      {/* WHY muted: supplemental data, lower visual priority than title/ticker */}
      {epsSnippet && (
        <span className="shrink-0 text-[10px] text-muted-foreground" title={event.description}>
          {epsSnippet}
        </span>
      )}
    </div>
  );
}
