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

  // ── Loading state ──────────────────────────────────────────────────────────
  if (isLoading) {
    return (
      <div className="space-y-2">
        {Array.from({ length: 4 }).map((_, i) => (
          <div key={i} className="flex gap-2">
            <Skeleton className="h-5 w-12" style={{ animationDelay: `${i * 50}ms` }} />
            <Skeleton className="h-5 flex-1" style={{ animationDelay: `${i * 50}ms` }} />
            <Skeleton className="h-5 w-8" style={{ animationDelay: `${i * 50}ms` }} />
          </div>
        ))}
      </div>
    );
  }

  // ── Error state ────────────────────────────────────────────────────────────
  // WHY muted (not destructive red): backend service offline is not a user error.
  // Muted text avoids making the dashboard look broken.
  if (isError) {
    return (
      <p className="text-sm text-muted-foreground">
        Economic calendar unavailable — events will appear once macro data is ingested.
      </p>
    );
  }

  const events = data?.events ?? [];

  if (events.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">No upcoming events</p>
    );
  }

  return (
    <div className="space-y-1">
      {events.slice(0, 8).map((event) => {
        const date = new Date(event.event_date);
        const dateStr = date.toISOString().slice(5, 10); // "MM-DD"
        const timeStr = date.toISOString().slice(11, 16); // "HH:MM"

        return (
          <div
            key={event.event_id}
            className="flex items-start gap-2 rounded px-1 py-0.5 hover:bg-muted/30"
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
            <p className="min-w-0 flex-1 truncate text-xs text-foreground" title={event.title}>
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
