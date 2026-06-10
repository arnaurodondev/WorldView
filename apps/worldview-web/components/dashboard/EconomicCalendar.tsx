/**
 * components/dashboard/EconomicCalendar.tsx — Upcoming macro events widget
 *
 * WHY THIS EXISTS: Economic events (Fed decisions, CPI, NFP) move markets.
 * Traders need to know what's coming in the next 48–72h to manage risk.
 * The calendar widget answers: "What do I need to be aware of today?"
 *
 * WHY IMPACT BADGE: HIGH impact events (Fed, CPI, GDP) require immediate
 * attention. Color coding lets traders scan the list in seconds rather
 * than reading each row.
 *
 * WHO USES IT: app/(app)/dashboard/page.tsx
 * DATA SOURCE: S9 GET /api/v1/fundamentals/economic-calendar → S7 temporal-events
 * DESIGN REFERENCE: PRD-0028 §6.5 Dashboard EconomicCalendar
 */

"use client";
// WHY "use client": uses useInfiniteQuery + interactive "Load more" button.

import { useInfiniteQuery, type InfiniteData } from "@tanstack/react-query";
import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
import { Skeleton } from "@/components/ui/skeleton";
// Round 3 (item 4): shared EmptyState primitive (§15.12) — copy key keeps
// the previously rendered strings verbatim.
import { EmptyState } from "@/components/primitives/EmptyState";
import { CalendarClock } from "lucide-react";
import type { EconomicCalendarResponse, EconomicImpact } from "@/types/api";

// ── Constants ─────────────────────────────────────────────────────────────────

/**
 * PAGE_SIZE — events fetched per page.
 *
 * WHY 10: matches the original visible row count (the previous version did
 * `.slice(0, 8)` which silently capped the list). 10 gives one extra row of
 * context per fetch while keeping the panel compact on first load.
 */
const PAGE_SIZE = 10;

// ── Component ─────────────────────────────────────────────────────────────────

export function EconomicCalendar() {
  const { accessToken } = useAuth();

  // WHY useInfiniteQuery: drives a "Load more" button that fetches the next
  // PAGE_SIZE events using offset-based pagination. The previous version used
  // .slice(0, 8) which silently dropped any further events the API returned
  // (Dashboard Regression #3). Now the user can page through the full window.
  const { data, isLoading, isError, fetchNextPage, hasNextPage, isFetchingNextPage } =
    useInfiniteQuery<
      EconomicCalendarResponse,
      Error,
      InfiniteData<EconomicCalendarResponse>,
      readonly unknown[],
      number
    >({
      queryKey: ["economic-calendar-infinite"],
      queryFn: ({ pageParam }) =>
        createGateway(accessToken).getEconomicCalendar({ limit: PAGE_SIZE, offset: pageParam }),
      // WHY 0 as initialPageParam: first page starts at offset=0.
      initialPageParam: 0,
      getNextPageParam: (lastPage, allPages) => {
        // WHY combine page-size signal + total count: if the server returned
        // a full page AND we've not yet seen all `total` events, there are
        // more pages. Otherwise we've reached the end.
        const loaded = allPages.reduce((n, p) => n + p.events.length, 0);
        const total = lastPage.total;
        if (total != null) return loaded < total ? loaded : undefined;
        // Fallback when backend doesn't return `total`: stop when we get a
        // partial page (server returned fewer rows than the page size).
        return lastPage.events.length === PAGE_SIZE ? loaded : undefined;
      },
      enabled: !!accessToken,
      // WHY 10min: economic events don't change frequently; 10min is fine
      staleTime: 10 * 60_000,
      refetchInterval: 10 * 60_000,
    });

  // WHY flatten across pages: each page is a slice of the leaderboard; we
  // render the concatenation as a single scrollable list.
  const events = data?.pages.flatMap((p) => p.events) ?? [];
  // WHY total fallback to events.length: when backend omits total we can still
  // hide the "Load more" button once we hit the end.
  const total = data?.pages[0]?.total ?? events.length;

  // WHY single outer wrapper for all render paths:
  // All states (loading, error, empty, data) live inside the same bg-background
  // h-full flex-col shell so the panel cell is consistently filled regardless of
  // data state — no "pop" from transparent empty state to filled data state.
  return (
    // WHY bg-background + h-full flex-col: consistent with EarningsCalendarWidget,
    // PortfolioNewsWidget, and PredictionMarketsWidget — all Row-4 panels use this
    // outer container pattern so the gap-px hairline separators look uniform.
    <div className="flex h-full flex-col bg-background">

      {/* ── Section header §0.9 pattern ──────────────────────────────────── */}
      <div className="flex h-6 shrink-0 items-center border-b border-border px-2">
        <span className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground">
          ECONOMIC CALENDAR
        </span>
      </div>

      {/* ── Loading state ──────────────────────────────────────────────── */}
      {/* SA-2 PLAN-0088 density: space-y-1.5 + py-1.5 (was space-y-2 + py-2).
          T-F-6-03: standardised inner content padding px-3 (unchanged). */}
      {/* Round 3 (item 3): skeleton rows now use the loaded list's exact
          geometry — h-[22px] divide-y rows at px-2 with the real column
          slots (date+time · title flex · forecast/previous · impact letter)
          instead of the previous taller spaced bars, so the event rows swap
          in with zero layout shift. 6 rows ≈ a typical first page fold. */}
      {isLoading && (
        <div className="flex-1 divide-y divide-border/30">
          {Array.from({ length: 6 }).map((_, i) => (
            <div key={i} className="flex h-[22px] items-center gap-2 px-2">
              <Skeleton className="h-3 w-[72px] shrink-0" style={{ animationDelay: `${i * 50}ms` }} />
              <Skeleton className="h-3 min-w-0 flex-1" style={{ animationDelay: `${i * 50}ms` }} />
              <Skeleton className="h-3 w-[64px] shrink-0" style={{ animationDelay: `${i * 50}ms` }} />
              <Skeleton className="h-3 w-3 shrink-0" style={{ animationDelay: `${i * 50}ms` }} />
            </div>
          ))}
        </div>
      )}

      {/* ── Error state ─────────────────────────────────────────────────── */}
      {/* WHY muted (not destructive red): backend service offline is not a user error.
          Muted text avoids making the dashboard look broken. */}
      {isError && (
        // T-F-6-03: standardised inner content padding px-3 py-2 (was px-2 pt-1)
        // WHY text-xs (was text-sm): dashboard tile error copy → 12px Bloomberg
        // standard. PLAN-0087 F-DENSITY-001.
        <p className="flex-1 px-3 py-2 text-xs text-muted-foreground">
          Economic calendar unavailable — events will appear once macro data is ingested.
        </p>
      )}

      {/* ── Empty state ─────────────────────────────────────────────────── */}
      {/* WHY descriptive message (not "No upcoming events"): the empty state here
          is caused by data not yet being ingested — not a calendar with no events.
          A clear message sets correct expectations: the API is functional but the
          economic event data stream hasn't populated yet. */}
      {/* T-F-6-03: standardised inner content padding px-3 py-2 (was px-2 pt-2) */}
      {/* Round 3 (item 4): shared EmptyState primitive — copy key
          dashboard.no-economic-events carries the exact strings that were
          hardcoded here, so the rationale (data-not-ingested, not "broken")
          and any text-matching tests are preserved. */}
      {!isLoading && !isError && events.length === 0 && (
        <div className="flex flex-1 items-center justify-center">
          <EmptyState
            condition="empty-no-data"
            copyKey="dashboard.no-economic-events"
            icon={CalendarClock}
          />
        </div>
      )}

      {/* ── Event rows ──────────────────────────────────────────────────── */}
      {/* WHY no .slice(): we now render every event the server returned across
          all loaded pages. The "Load more" button at the bottom drives the
          next page fetch via useInfiniteQuery.fetchNextPage(). */}
      {!isLoading && !isError && events.length > 0 && (
        <div className="flex-1 divide-y divide-border/30 overflow-auto">
          {events.map((event) => {
            const date = new Date(event.event_date);
            const dateStr = date.toISOString().slice(5, 10); // "MM-DD"
            const timeStr = date.toISOString().slice(11, 16); // "HH:MM"

            return (
              <div
                key={event.event_id}
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

                {/* Event name */}
                <p className="min-w-0 flex-1 truncate text-[11px] text-foreground" title={event.title}>
                  {event.title}
                </p>

                {/* Forecast vs previous — monospace for alignment */}
                {(event.forecast !== null || event.previous !== null) && (
                  <div className="flex shrink-0 gap-1 text-[10px] text-muted-foreground">
                    {event.forecast !== null && (
                      <span className="font-mono tabular-nums" title="Forecast">
                        F: {formatEconomicValue(event.forecast, event.unit)}
                      </span>
                    )}
                    {event.previous !== null && (
                      <span className="font-mono tabular-nums" title="Previous">
                        P: {formatEconomicValue(event.previous, event.unit)}
                      </span>
                    )}
                  </div>
                )}

                {/* Impact badge */}
                <ImpactBadge impact={event.impact} />
              </div>
            );
          })}

          {/* ── Load more button ──────────────────────────────────────── */}
          {/* WHY render at the bottom of the scrollable list: discoverability
              — user scrolls to the bottom and sees the action. We only render
              when hasNextPage is true so the panel stays clean at end-of-list. */}
          {hasNextPage && (
            <div className="flex items-center justify-center border-t border-border/30 px-2 py-1">
              <button
                type="button"
                onClick={() => fetchNextPage()}
                disabled={isFetchingNextPage}
                // Round 3 (item 5): hover bg + keyboard focus ring on the pager.
                className="px-1.5 text-[10px] uppercase tracking-[0.08em] text-muted-foreground transition-colors hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:pointer-events-none"
              >
                {isFetchingNextPage
                  ? "Loading…"
                  : `Load more (${events.length}/${total})`}
              </button>
            </div>
          )}
        </div>
      )}

    </div>
  );
}

// ── Sub-components ─────────────────────────────────────────────────────────────

function ImpactBadge({ impact }: { impact: EconomicImpact }) {
  // WHY inline styles (not tailwind classes): dynamic colors from impact level
  const colors: Record<EconomicImpact, string> = {
    HIGH: "text-warning", // PLAN-0059 W0 F-VISUAL-022: --warning token (was amber-400)
    MEDIUM: "text-muted-foreground",
    LOW: "text-muted-foreground/50",
  };

  return (
    <span className={`shrink-0 text-[9px] font-semibold uppercase tracking-wider ${colors[impact]}`}>
      {impact.slice(0, 1)} {/* H / M / L — single letter for narrow column */}
    </span>
  );
}

// ── Helpers ───────────────────────────────────────────────────────────────────

/** formatEconomicValue — format numeric values with optional unit suffix */
function formatEconomicValue(value: number, unit: string | null): string {
  if (unit === "%" || unit === "bps") {
    return `${value.toFixed(1)}${unit}`;
  }
  if (Math.abs(value) >= 1_000_000) {
    return `${(value / 1_000_000).toFixed(1)}M`;
  }
  if (Math.abs(value) >= 1_000) {
    return `${(value / 1_000).toFixed(0)}K`;
  }
  return value.toFixed(1);
}
