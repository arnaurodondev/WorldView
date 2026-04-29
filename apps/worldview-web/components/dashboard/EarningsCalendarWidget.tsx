/**
 * components/dashboard/EarningsCalendarWidget.tsx — Upcoming earnings placeholder
 *
 * WHY THIS EXISTS: Earnings calendars are a critical part of the morning routine —
 * traders need to know which companies report today or this week to anticipate
 * volatility. This widget reserves the dashboard slot structurally with a clear
 * "coming soon" state while the earnings data integration is built.
 *
 * WHY PLACEHOLDER (not omit entirely): Structural presence in the 12-column grid
 * is intentional — removing this cell would leave an odd col-span gap. The
 * placeholder communicates the roadmap intent to traders while keeping the layout
 * symmetric with EconomicCalendar in the same row.
 *
 * WHO USES IT: app/(app)/dashboard/page.tsx (Row 4, col-span-3)
 * DATA SOURCE: Placeholder — earnings calendar integration pending
 * DESIGN REFERENCE: PRD-0031 §10 Dashboard Wave 7
 */

// WHY no "use client": pure presentational, no hooks or browser APIs.
// WHY no InlineEmptyState import: we use plain <p> elements for the empty state
// here — the two-line message layout doesn't match InlineEmptyState's single-line
// API, and avoids pulling in an unnecessary dependency for a static component.

// ── Component ─────────────────────────────────────────────────────────────────

/**
 * EarningsCalendarWidget — static placeholder for upcoming earnings events.
 */
export function EarningsCalendarWidget() {
  return (
    // WHY bg-background: consistent with all other dashboard widgets — the
    // gap-px grid's background bleed already provides the hairline panel borders.
    // bg-card would create a visually raised surface that mismatches the flat
    // terminal aesthetic used by PortfolioNewsWidget, PredictionMarketsWidget, etc.
    <div className="flex h-full flex-col bg-background">

      {/* ── Section header §0.9 pattern ──────────────────────────────────── */}
      <div className="flex h-6 shrink-0 items-center border-b border-border px-2">
        <span className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground">
          EARNINGS CALENDAR
        </span>
      </div>

      {/* ── Empty state ────────────────────────────────────────────────────── */}
      {/* WHY two-line message: first line tells what is missing; second line tells
          WHY it is missing (data not ingested). This avoids confusion where traders
          might think the widget is broken rather than awaiting data ingest. */}
      {/* T-F-6-03: standardised inner content padding px-3 py-2 (was px-2 pt-2) */}
      <div className="flex flex-1 flex-col gap-0.5 px-3 py-2">
        <p className="text-xs text-muted-foreground">No upcoming earnings events scheduled.</p>
        <p className="text-[10px] text-muted-foreground/60">
          Earnings calendar data populates as company reporting schedules are ingested.
        </p>
      </div>

    </div>
  );
}
