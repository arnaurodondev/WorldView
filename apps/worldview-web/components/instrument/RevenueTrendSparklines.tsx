/**
 * components/instrument/RevenueTrendSparklines.tsx — Revenue trend placeholder
 *
 * WHY THIS EXISTS: The Fundamentals tab needs a Revenue Trend section above
 * the metrics grid. Quarterly revenue bars contextualize the YoY growth metrics
 * in the Growth section — a 28% YoY growth means more if you can see the trend
 * was actually decelerating over the last 4 quarters.
 *
 * WHY PLACEHOLDER: The Fundamentals type only has `revenue_growth_yoy` (a single
 * annual figure), not quarterly time-series data. The Financials.Quarterly endpoint
 * from EODHD exists (S3 fetches it) but the data has not been surfaced through S9
 * yet. This component establishes the section structure for a future wave.
 *
 * WHY ALWAYS RENDER (not return null): Same Bloomberg convention as AnalystConsensusStrip —
 * the section header should appear to signal that this data category is tracked.
 *
 * WHO USES IT: FundamentalsTab.tsx (full-width section above the metrics grid)
 * DATA SOURCE: Props from FundamentalsTab (no independent fetch; data pending)
 * DESIGN REFERENCE: PRD-0031 §9 FundamentalsTab 9 sections, Wave 5
 */

// WHY no "use client": pure display component — no hooks, no browser APIs.

import { InlineEmptyState } from "@/components/data/InlineEmptyState";
import type { Fundamentals } from "@/types/api";

// ── Props ─────────────────────────────────────────────────────────────────────

interface RevenueTrendSparklinesProps {
  fundamentals: Fundamentals | null;
}

// ── Component ─────────────────────────────────────────────────────────────────

export function RevenueTrendSparklines({ fundamentals: _fundamentals }: RevenueTrendSparklinesProps) {
  // WHY _fundamentals (prefixed underscore): the parameter is not yet used since
  // quarterly data is not in the Fundamentals type. The underscore signals intentional
  // non-use while keeping the prop for future implementation. When quarterly fields
  // are added, this component will render actual sparklines from the data.

  return (
    <div>
      <div className="flex items-center border-b border-border px-2 h-6">
        <span className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground">
          REVENUE TREND
        </span>
      </div>

      {/* WHY InlineEmptyState with "pending" message (not null): establishes the
          section structure so analysts know this data category will be available. */}
      <InlineEmptyState
        message="Quarterly revenue data pending"
        className="px-2 py-1.5 text-[11px]"
      />
    </div>
  );
}
