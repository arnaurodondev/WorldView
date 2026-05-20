/**
 * components/instrument/intelligence/news/NewsFilters.tsx — T-D-02
 *
 * WHY: 32px filter strip above NewsColumn. Time tabs + sentiment pills.
 * WHY underline tabs: Bloomberg/Finviz inline-filter convention.
 * WHY parent owns state: NewsColumn keys its fetch off these values.
 */

"use client";

import { cn } from "@/lib/utils";

export type NewsTimeRange = "all" | "day" | "3d" | "1w";
export type NewsSentiment = "positive" | "neutral" | "negative" | null;

interface NewsFiltersProps {
  timeRange: NewsTimeRange;
  onTimeRangeChange: (value: NewsTimeRange) => void;
  sentiment: NewsSentiment;
  onSentimentChange: (value: NewsSentiment) => void;
}

// Module-scope so React doesn't re-allocate these on every render.
const TIME_TABS: ReadonlyArray<[NewsTimeRange, string]> = [
  ["all", "ALL"], ["day", "TODAY"], ["3d", "3D"], ["1w", "1W"],
];
const SENTIMENT_TABS: ReadonlyArray<[NonNullable<NewsSentiment>, string]> = [
  ["positive", "POS"], ["neutral", "NEU"], ["negative", "NEG"],
];

const TAB = "text-[10px] uppercase tracking-wide pb-1 transition-colors";
const ACTIVE = "border-b-2 border-primary text-foreground";
const IDLE = "text-muted-foreground hover:text-foreground";

export function NewsFilters({
  timeRange, onTimeRangeChange, sentiment, onSentimentChange,
}: NewsFiltersProps) {
  // h-8 + px-3 matches the 32px filter-strip baseline (DESIGN_SYSTEM.md).
  return (
    <div className="h-8 border-b border-border flex items-center px-3 gap-4">
      <div className="flex items-center gap-3">
        {TIME_TABS.map(([v, label]) => (
          <button
            key={v}
            type="button"
            onClick={() => onTimeRangeChange(v)}
            className={cn(TAB, timeRange === v ? ACTIVE : IDLE)}
          >
            {label}
          </button>
        ))}
      </div>
      <span className="text-muted-foreground/40 text-[10px]">|</span>
      <div className="flex items-center gap-3 ml-auto">
        {SENTIMENT_TABS.map(([v, label]) => (
          // WHY toggle-to-null: click active = clear (Bloomberg convention).
          <button
            key={v}
            type="button"
            onClick={() => onSentimentChange(sentiment === v ? null : v)}
            className={cn(TAB, sentiment === v ? ACTIVE : IDLE)}
          >
            {label}
          </button>
        ))}
      </div>
    </div>
  );
}
