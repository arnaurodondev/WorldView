/**
 * features/portfolio/components/AnalyticsPeriodSelector.tsx
 *
 * WHY THIS EXISTS: Provides a compact pill-group period selector for the
 * Analytics tab. Modelled after TradingView's period-pill row — same visual
 * pattern users recognise from the workspace chart toolbar. Purely
 * presentational: the caller (AnalyticsTab) owns state via nuqs and passes
 * value/onChange down. Keeping it stateless makes it trivially testable.
 *
 * WHY "use client": uses props/callbacks (no hooks), but co-located with
 * client components and imported from them — mark it early.
 *
 * DESIGN REFERENCE: docs/designs/0089/04-portfolio-detail.md §4.3
 */
"use client";

// WHY cn: conditional class composition without string concatenation bugs.
import { cn } from "@/lib/utils";

// ── Types ─────────────────────────────────────────────────────────────────────

export interface AnalyticsPeriodSelectorProps {
  /** Currently active period string (e.g. "YTD"). */
  value: string;
  /** Called with the newly selected period when a pill is clicked. */
  onChange: (p: string) => void;
}

// ── Period list ───────────────────────────────────────────────────────────────

// WHY these specific periods: match the analytics design spec §4.3 which
// mirrors IBKR's "Time Period Analyzer" — 7 breakpoints from 1M through ALL
// give enough granularity to distinguish short-term volatility from long-term
// trend without overcrowding the pill row.
const PERIODS = ["1M", "3M", "6M", "YTD", "1Y", "2Y", "ALL"] as const;

export type AnalyticsPeriod = (typeof PERIODS)[number];

// ── Component ─────────────────────────────────────────────────────────────────

export function AnalyticsPeriodSelector({
  value,
  onChange,
}: AnalyticsPeriodSelectorProps) {
  return (
    // WHY role="tablist" + role="tab": pill-group period selectors are
    // semantically tab-like (mutually exclusive selection). This enables
    // arrow-key navigation for a11y without custom keyboard handlers.
    <div
      role="tablist"
      aria-label="Analytics period"
      className="flex items-center gap-0.5"
    >
      {PERIODS.map((p) => {
        const isActive = value === p;
        return (
          <button
            key={p}
            role="tab"
            aria-selected={isActive}
            onClick={() => onChange(p)}
            className={cn(
              // WHY font-mono: all numeric/period labels in this app use
              // font-mono to maintain consistent visual rhythm and avoid
              // layout shift when period length differs (e.g. "1M" vs "YTD").
              "text-[11px] font-mono px-2 py-0.5 rounded transition-colors",
              isActive
                ? // Active pill: primary background mirrors the active tab
                  // pattern used in PortfolioTabs and the workspace chart toolbar.
                  "bg-primary text-primary-foreground"
                : // Inactive pill: muted with hover uplift so the tap target is
                  // visually obvious without overwhelming the chart.
                  "bg-muted text-muted-foreground hover:text-foreground hover:bg-muted/80",
            )}
          >
            {p}
          </button>
        );
      })}
    </div>
  );
}
