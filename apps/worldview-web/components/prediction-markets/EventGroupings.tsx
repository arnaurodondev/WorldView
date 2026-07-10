/**
 * components/prediction-markets/EventGroupings.tsx — Polymarket event groups
 * (PLAN-0056 Wave E2, task 5).
 *
 * WHAT AN "EVENT" IS: Polymarket groups related markets under an event (e.g.
 * "2024 US Presidential Election" groups dozens of state/candidate markets).
 * This section lists those groups so a trader can see the thematic clusters.
 *
 * ── HONEST DATA LIMITATION ──
 * The `/events` list returns group HEADERS only (name, category, market_count) —
 * S3 has no event_id→child-markets edge on the wire yet. So we CANNOT nest the
 * individual market rows under each group without fabricating membership. This
 * section therefore renders each event as a COLLAPSIBLE header that expands to
 * the group's metadata (category, date window, market count), not a list of the
 * child markets. When S3 exposes membership, the expanded body is where those
 * rows will slot in. Documented in docs/apps/worldview-web.md.
 *
 * The whole section is itself collapsible (starts collapsed) so it never crowds
 * the flat market list above it — it's opt-in context.
 */

"use client";
// WHY "use client": query hook + local expand/collapse state.

import { useState } from "react";
import { usePredictionEvents } from "@/lib/api/prediction-markets-hooks";
import { Skeleton } from "@/components/ui/skeleton";
import { ChevronRight, ChevronDown, Layers } from "lucide-react";
import { cn } from "@/lib/utils";

/** Format a start–end window as "Jul 3 – Aug 1", or one side, or "" when absent. */
function formatWindow(start: string | null, end: string | null): string {
  const fmt = (iso: string) =>
    new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", timeZone: "UTC" }).format(
      new Date(iso),
    );
  const s = start ? fmt(start) : "";
  const e = end ? fmt(end) : "";
  if (s && e) return `${s} – ${e}`;
  return s || e;
}

// ── Single collapsible event row ────────────────────────────────────────────────
function EventRow({
  name,
  category,
  marketCount,
  window,
}: {
  name: string;
  category: string | null;
  marketCount: number;
  window: string;
}) {
  const [open, setOpen] = useState(false);
  return (
    <div data-testid="event-row" className="border-b border-border/30">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex w-full items-center gap-2 px-3 py-1.5 text-left hover:bg-card/60"
      >
        {open ? (
          <ChevronDown className="h-3 w-3 shrink-0 text-muted-foreground" strokeWidth={1.5} />
        ) : (
          <ChevronRight className="h-3 w-3 shrink-0 text-muted-foreground" strokeWidth={1.5} />
        )}
        <span className="min-w-0 flex-1 truncate text-[11px] text-foreground">{name}</span>
        {category && (
          <span className="shrink-0 rounded-[2px] bg-muted/40 px-1.5 py-0.5 font-mono text-[9px] uppercase tracking-wider text-muted-foreground">
            {category}
          </span>
        )}
        <span className="shrink-0 font-mono text-[9px] tabular-nums text-muted-foreground">
          {marketCount} mkt
        </span>
      </button>
      {open && (
        <div data-testid="event-row-body" className="px-3 pb-2 pl-8">
          <div className="space-y-0.5 font-mono text-[9px] text-muted-foreground">
            <div className="flex gap-2">
              <span className="w-16 text-muted-foreground/60">Markets</span>
              <span className="tabular-nums text-foreground/80">{marketCount}</span>
            </div>
            {window && (
              <div className="flex gap-2">
                <span className="w-16 text-muted-foreground/60">Window</span>
                <span className="text-foreground/80">{window}</span>
              </div>
            )}
            {/* Honest note: child-market membership isn't on the wire yet. */}
            <p className="pt-1 text-muted-foreground/50">
              Individual markets in this event aren&apos;t linked in the feed yet.
            </p>
          </div>
        </div>
      )}
    </div>
  );
}

export function EventGroupings() {
  // Section starts collapsed — it's supplementary context to the flat list.
  const [sectionOpen, setSectionOpen] = useState(false);
  const { data, isLoading, isError } = usePredictionEvents({ limit: 25 });

  const events = data?.items ?? [];
  // Hide the whole section when there are genuinely no events (avoids an empty
  // toggle that expands to nothing).
  if (!isLoading && !isError && events.length === 0) return null;

  return (
    <div data-testid="event-groupings" className="border-b border-border/50">
      <button
        type="button"
        onClick={() => setSectionOpen((v) => !v)}
        aria-expanded={sectionOpen}
        className="flex w-full items-center gap-2 px-3 py-1.5 hover:bg-card/60"
      >
        <Layers className="h-3.5 w-3.5 text-muted-foreground" strokeWidth={1.5} />
        <span className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
          Events
        </span>
        {events.length > 0 && (
          <span className="font-mono text-[9px] tabular-nums text-muted-foreground/70">
            {events.length}
          </span>
        )}
        <span className="ml-auto">
          {sectionOpen ? (
            <ChevronDown className="h-3.5 w-3.5 text-muted-foreground" strokeWidth={1.5} />
          ) : (
            <ChevronRight className="h-3.5 w-3.5 text-muted-foreground" strokeWidth={1.5} />
          )}
        </span>
      </button>

      {sectionOpen && (
        <div className={cn("bg-background/40")}>
          {isLoading &&
            Array.from({ length: 3 }).map((_, i) => (
              <div key={i} className="px-3 py-1.5">
                <Skeleton className="h-3 w-2/3" />
              </div>
            ))}
          {isError && (
            <p className="px-3 py-2 text-[10px] text-muted-foreground">Couldn&apos;t load events</p>
          )}
          {!isLoading &&
            !isError &&
            events.map((ev) => (
              <EventRow
                key={ev.event_id}
                name={ev.name}
                category={ev.category}
                marketCount={ev.market_count}
                window={formatWindow(ev.start_date, ev.end_date)}
              />
            ))}
        </div>
      )}
    </div>
  );
}
