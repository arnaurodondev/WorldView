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
// WHY "use client": uses useQuery.

import { useQuery } from "@tanstack/react-query";
import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
import { Skeleton } from "@/components/ui/skeleton";
import type { EconomicImpact } from "@/types/api";

// ── Component ─────────────────────────────────────────────────────────────────

export function EconomicCalendar() {
  const { accessToken } = useAuth();

  const { data, isLoading, isError } = useQuery({
    queryKey: ["economic-calendar"],
    queryFn: () => createGateway(accessToken).getEconomicCalendar(),
    enabled: !!accessToken,
    // WHY 10min: economic events don't change frequently; 10min is fine
    staleTime: 10 * 60_000,
    refetchInterval: 10 * 60_000,
  });

  const events = data?.events ?? [];

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
      {isLoading && (
        <div className="flex-1 space-y-2 px-2 pt-1">
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="flex gap-2">
              <Skeleton className="h-5 w-12" style={{ animationDelay: `${i * 50}ms` }} />
              <Skeleton className="h-5 flex-1" style={{ animationDelay: `${i * 50}ms` }} />
              <Skeleton className="h-5 w-8" style={{ animationDelay: `${i * 50}ms` }} />
            </div>
          ))}
        </div>
      )}

      {/* ── Error state ─────────────────────────────────────────────────── */}
      {/* WHY muted (not destructive red): backend service offline is not a user error.
          Muted text avoids making the dashboard look broken. */}
      {isError && (
        <p className="flex-1 px-2 pt-1 text-sm text-muted-foreground">
          Economic calendar unavailable — events will appear once macro data is ingested.
        </p>
      )}

      {/* ── Empty state ─────────────────────────────────────────────────── */}
      {!isLoading && !isError && events.length === 0 && (
        <p className="flex-1 px-2 pt-1 text-sm text-muted-foreground">No upcoming events</p>
      )}

      {/* ── Event rows ──────────────────────────────────────────────────── */}
      {!isLoading && !isError && events.length > 0 && (
        <div className="flex-1 divide-y divide-border/30 overflow-auto">
          {events.slice(0, 8).map((event) => {
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
        </div>
      )}

    </div>
  );
}

// ── Sub-components ─────────────────────────────────────────────────────────────

function ImpactBadge({ impact }: { impact: EconomicImpact }) {
  // WHY inline styles (not tailwind classes): dynamic colors from impact level
  const colors: Record<EconomicImpact, string> = {
    HIGH: "text-amber-400",
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
