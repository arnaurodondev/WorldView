/**
 * events/EventsBlock.tsx — entity-scoped temporal events for the Intelligence
 * tab's right rail (PLAN-0099 Wave 2).
 *
 * WHY THIS EXISTS: Wave 1 shipped GET /v1/entities/{id}/events — temporal
 * events (regulatory threats, macro shocks, earnings windows) the KG exposes
 * for this entity via entity_event_exposures, each with a computed
 * lifecycle_phase. The investigation page surfaces them between NEWS (raw
 * coverage) and CONTRADICTIONS (data-quality signals): events are the curated
 * "what is structurally happening to this entity" layer.
 *
 * ROW ANATOMY (22px house rhythm): event-type chip · title · lifecycle chip ·
 * date (mono). Title expands on hover via the title attribute; description
 * is shown as the tooltip when present.
 *
 * DATA SOURCE: useEntityEvents(entityId) → active_only=false, limit=20.
 * WHO USES IT: IntelligenceTab right rail.
 */

"use client";
// WHY "use client": TanStack Query hook requires browser React.

import { CalendarClock } from "lucide-react";
import { useEntityEvents } from "@/lib/api/intelligence";
import { Skeleton } from "@/components/ui/skeleton";
import { cn, formatDate } from "@/lib/utils";
import type { EntityEventItem } from "@/lib/api/knowledge-graph";

// ── Props ────────────────────────────────────────────────────────────────────

export interface EventsBlockProps {
  readonly entityId: string;
}

// ── Helpers ──────────────────────────────────────────────────────────────────

/**
 * lifecycle phase → semantic token classes.
 * ACTIVE = warning (the event is live — pay attention now);
 * PENDING = primary tint (upcoming); RESIDUAL = muted-warning tail;
 * EXPIRED/unknown = muted (historical context only).
 */
function phaseClass(phase: string | null | undefined): string {
  const p = (phase ?? "").toUpperCase();
  if (p === "ACTIVE") return "text-warning bg-warning/15";
  if (p === "PENDING") return "text-primary bg-primary/10";
  if (p === "RESIDUAL") return "text-warning/70 bg-warning/10";
  return "text-muted-foreground bg-muted";
}

// ── Sub-component: one event row ─────────────────────────────────────────────

function EventRow({ event }: { event: EntityEventItem }) {
  const phase = (event.lifecycle_phase ?? "—").toUpperCase();
  return (
    <li
      // 22px row — the house dense-row unit; hover bg for scannability.
      className="flex items-center gap-1.5 h-[22px] px-2 hover:bg-muted/30 min-w-0"
      data-testid={`event-row-${event.event_id}`}
    >
      {/* Event-type chip — snake_case → spaces, uppercase mono. */}
      {event.event_type && (
        <span className="shrink-0 text-[9px] font-mono uppercase tracking-wider bg-muted text-muted-foreground px-1 py-0.5 rounded-[2px]">
          {event.event_type.replace(/_/g, " ")}
        </span>
      )}
      <span
        className="flex-1 truncate text-[11px] text-foreground/80"
        // Tooltip carries the full title + optional description — the dense
        // row cannot afford a second line.
        title={event.description ? `${event.title ?? ""} — ${event.description}` : (event.title ?? undefined)}
      >
        {event.title ?? "Untitled event"}
      </span>
      {/* Lifecycle chip — the phase signal is the reason this block exists. */}
      <span
        className={cn(
          "shrink-0 text-[9px] font-mono uppercase tracking-wider px-1 py-0.5 rounded-[2px]",
          phaseClass(event.lifecycle_phase),
        )}
      >
        {phase}
      </span>
      {event.active_from && (
        <span className="shrink-0 font-mono text-[9px] tabular-nums text-muted-foreground/70">
          {formatDate(event.active_from)}
        </span>
      )}
    </li>
  );
}

// ── Component ────────────────────────────────────────────────────────────────

export function EventsBlock({ entityId }: EventsBlockProps) {
  const { data, isLoading, isError, refetch } = useEntityEvents(entityId);

  // Accent-bar header — always rendered (the rail's section skeleton must not
  // jump when data lands); the count badge fills in once loaded.
  const header = (
    <div className="flex items-center justify-between border-y border-border border-l-2 border-l-primary bg-muted/20 h-[18px] px-2">
      <span className="text-[9px] uppercase tracking-widest text-muted-foreground/70 font-medium">
        Events
      </span>
      {data != null && (
        <span className="font-mono text-[9px] tabular-nums text-muted-foreground">{data.total}</span>
      )}
    </div>
  );

  if (isLoading) {
    return (
      <section aria-label="Entity events loading">
        {header}
        {/* Shape-matched static row bars (DS §6.2 — skeletons never animate). */}
        <div className="px-2 py-1 space-y-1" data-testid="events-skeleton" aria-hidden>
          <Skeleton className="h-[18px] w-full" />
          <Skeleton className="h-[18px] w-full" />
          <Skeleton className="h-[18px] w-4/5" />
        </div>
      </section>
    );
  }

  // NAMED per-section error + retry — errors are not emptiness (Round-4 rule).
  if (isError) {
    return (
      <section aria-label="Entity events">
        {header}
        <div
          data-testid="events-fetch-error"
          className="flex flex-col items-center gap-1 px-3 py-3 text-center"
        >
          <p className="text-[12px] text-foreground">Couldn&apos;t load events</p>
          <p className="text-[11px] text-muted-foreground">Other panels are unaffected.</p>
          <button
            type="button"
            onClick={() => void refetch()}
            className="mt-0.5 font-mono text-[9px] uppercase tracking-wider text-primary hover:underline focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring rounded-[2px]"
          >
            Retry
          </button>
        </div>
      </section>
    );
  }

  const events = data?.events ?? [];

  return (
    <section aria-label="Entity events">
      {header}
      {events.length === 0 ? (
        // Named empty — zero exposures is a normal state for quiet entities.
        <div
          role="status"
          data-testid="events-empty"
          className="flex flex-col items-center gap-1 px-3 py-3 text-center"
        >
          <CalendarClock className="size-4 text-muted-foreground/60" strokeWidth={1.5} aria-hidden />
          <p className="text-[12px] text-foreground">No events for this entity</p>
          <p className="text-[11px] text-muted-foreground">
            Temporal events appear when the pipeline links this entity to one.
          </p>
        </div>
      ) : (
        <ul role="list" className="py-0.5">
          {events.map((e) => (
            <EventRow key={e.event_id} event={e} />
          ))}
        </ul>
      )}
    </section>
  );
}
