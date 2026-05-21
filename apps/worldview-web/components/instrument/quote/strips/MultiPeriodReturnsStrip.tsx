/**
 * components/instrument/quote/strips/MultiPeriodReturnsStrip.tsx
 * — 7-period return strip (W5-T-09)
 *
 * WHY THIS EXISTS:
 *   Shows close-on-close percentage returns for 1D/5D/1M/3M/6M/YTD/1Y in a
 *   single horizontal band below the OHLCV chart. Terminal traders need
 *   multi-period context at a glance — scrolling through separate charts is
 *   a UX regression vs any Bloomberg terminal.
 *
 * DATA SOURCE: GET /v1/fundamentals/{id}/multi-period-returns (T-S9-03).
 *   Computed by S9 from the most recent 550 daily bars. Null for periods with
 *   insufficient history (e.g. stocks < 1Y since IPO).
 *
 * DESIGN DECISIONS:
 *   - `<div data-table-grid>` parent → 20px row height (Δ4, F1 §16.3).
 *   - `text-[10px]` labels (F1 floor, Δ2). `text-[11px] font-mono tabular-nums` values.
 *   - Semantic color: positive (green), negative (red), muted (null/zero). (Δ29)
 *   - No `rounded-*` anywhere (Δ3, F1 rounded=0).
 *   - 7 equal-width cells in a single flex row.
 *
 * WHO USES IT: QuoteTab.tsx (T-25 wiring pass). Props come from
 *   useQuoteSidebarData (T-05).
 *
 * LINE LIMIT: ≤ 110 LOC (plan).
 */

// WHY no "use client": pure display — props only, no browser APIs.

import type { MultiPeriodReturnsResponse } from "@/types/api";
import { MetricCell } from "@/components/primitives/MetricCell";

// ── Constants ────────────────────────────────────────────────────────────────

/** Ordered period labels — matches the backend contract and the visual left-to-right reading order. */
const PERIODS = ["1D", "5D", "1M", "3M", "6M", "YTD", "1Y"] as const;
type Period = (typeof PERIODS)[number];

// ── Helpers ───────────────────────────────────────────────────────────────────

/**
 * Format a return percentage for display.
 * null → undefined (MetricCell renders "—").
 * ±0.00% → "0.00%".
 * Preserves the sign: "+3.47%" for gains, "−3.47%" for losses.
 * WHY two decimal places: industry standard for period returns (not 1dp).
 */
function formatReturn(value: number | null | undefined): string | undefined {
  if (value === null || value === undefined) return undefined;
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toFixed(2)}%`;
}

/** Map a return value to a MetricCell color intent. */
function returnColor(value: number | null | undefined): "positive" | "negative" | "muted" {
  if (value === null || value === undefined || value === 0) return "muted";
  return value > 0 ? "positive" : "negative";
}

// ── Props ─────────────────────────────────────────────────────────────────────

interface MultiPeriodReturnsStripProps {
  /** Raw response from GET /v1/fundamentals/{id}/multi-period-returns. */
  data: MultiPeriodReturnsResponse | undefined;
  /** True while the query is loading — renders skeleton-like "—" cells. */
  isLoading?: boolean;
}

// ── Component ─────────────────────────────────────────────────────────────────

export function MultiPeriodReturnsStrip({
  data,
  isLoading = false,
}: MultiPeriodReturnsStripProps) {
  // On loading, all values are undefined → MetricCell renders "—" placeholders.
  // This is the preferred approach over a Skeleton overlay because the grid
  // structure is immediately visible and there's no layout shift on load.
  const periods = data?.periods;

  return (
    // WHY data-table-grid: F1 §16.3 opt-in — sets --row-h=20px, inner borders
    //   via [role="cell"] rules. (Δ4)
    // WHY border-b border-[hsl(var(--border-subtle))]: bottom hairline separates
    //   this strip from the IntradayStatsBand below. (Δ5)
    <div
      data-table-grid
      className="border-b border-[hsl(var(--border-subtle))]"
      aria-label="Multi-period price returns"
      // WHY role="row": the strip is a single data row in the data-table-grid
      //   context; [data-table-grid] [role="row"] { height: var(--row-h) } applies.
      role="row"
    >
      {/* WHY `min-w-0 flex-1` on each cell wrapper: equal-width cells that
          shrink below content-width on smaller viewports without overflowing.
          The 7 cells share the strip's full width. */}
      <div className="flex h-full">
        {PERIODS.map((period: Period) => {
          const raw = periods?.[period] ?? null;
          return (
            <div key={period} className="min-w-0 flex-1">
              <MetricCell
                label={period}
                value={isLoading ? undefined : formatReturn(raw)}
                color={isLoading ? "muted" : returnColor(raw)}
                align="right"
              />
            </div>
          );
        })}
      </div>
    </div>
  );
}
