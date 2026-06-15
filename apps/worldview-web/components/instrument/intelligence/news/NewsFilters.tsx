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
  //
  // UI CLARITY (2026-06-15): the strip previously showed two bare tab groups
  // separated by a "|" with no indication of what each controls. An analyst
  // landing on the tab could not tell that the left group narrows by TIME and
  // the right group by SENTIMENT. We added muted group LABELS ("WHEN" /
  // "TONE") — short enough to fit the 32px row, explicit enough that the
  // controls are self-describing. The labels use the same 9px-mono register as
  // the rail headers elsewhere on the tab for visual consistency.
  return (
    <div className="h-8 border-b border-border flex items-center px-3 gap-3">
      {/* Time-range group — narrows the feed by published_at (real S6
          start_date narrowing, handled in useEntityNewsInfinite). */}
      <span className="text-[9px] font-mono uppercase tracking-widest text-muted-foreground/50">
        When
      </span>
      <div className="flex items-center gap-3" role="group" aria-label="Filter news by time range">
        {TIME_TABS.map(([v, label]) => (
          <button
            key={v}
            type="button"
            onClick={() => onTimeRangeChange(v)}
            aria-pressed={timeRange === v}
            className={cn(TAB, timeRange === v ? ACTIVE : IDLE)}
          >
            {label}
          </button>
        ))}
      </div>
      <span className="text-muted-foreground/30 text-[10px]" aria-hidden>|</span>
      {/* Sentiment group — narrows the ALREADY-FETCHED feed client-side on each
          article's sentiment field (S6 has no sentiment query param). */}
      <span className="ml-auto text-[9px] font-mono uppercase tracking-widest text-muted-foreground/50">
        Tone
      </span>
      <div className="flex items-center gap-3" role="group" aria-label="Filter news by sentiment">
        {SENTIMENT_TABS.map(([v, label]) => (
          // WHY toggle-to-null: click active = clear (Bloomberg convention).
          <button
            key={v}
            type="button"
            onClick={() => onSentimentChange(sentiment === v ? null : v)}
            aria-pressed={sentiment === v}
            className={cn(TAB, sentiment === v ? ACTIVE : IDLE)}
          >
            {label}
          </button>
        ))}
      </div>
    </div>
  );
}
