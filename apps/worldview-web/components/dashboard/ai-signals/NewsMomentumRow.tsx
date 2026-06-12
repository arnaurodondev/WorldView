/**
 * components/dashboard/ai-signals/NewsMomentumRow.tsx — one news-momentum row
 *
 * WHY THIS EXISTS: the pre-pivot widget rendered "BSX ——— 95%" rows where the
 * 95% was a meaningless extraction confidence. This component renders one row
 * per RECENT NEWS STORY with everything a user needs to act:
 *
 *   ▼  Nvidia Breaks Below $200, Approaches Bear …   yahoo   83%  4m
 *   └─ click → opens the source article in a new tab
 *
 *  - sentiment dot (color + glyph, redundant encoding for color-blind users)
 *  - the headline (the event itself), truncated, links OUT to the publisher
 *  - short source label derived from the URL host ("yahoo", "fxstreet")
 *  - HONEST relevance % (display_relevance_score) with a tooltip explaining it
 *  - relative time so the user knows WHEN
 *
 * WHY the row links OUT to the article (target=_blank) instead of into our app:
 * the user's question is "what's moving in the news right now?" — the answer is
 * the story, and the story lives at the publisher. (The instrument page is a
 * click away from anywhere a ticker is shown; this feed is article-first.)
 *
 * WHO USES IT: AiSignalsWidget.tsx (one per NewsMomentumItem)
 * DESIGN REFERENCE: DESIGN_SYSTEM §0 terminal density (22px rows), §15.9
 * mono numerics, §15.11 semantic color utilities.
 */

"use client";
// WHY "use client": renders an interactive anchor with an onClick guard; kept
// client-side for parity with the rest of the widget (and future hooks).

import { cn } from "@/lib/utils";

import { compactRelativeTime, relevancePct, relevanceTitle, rowTitle, sentimentMeta } from "./news-meta";
import type { NewsMomentumItem } from "./types";

interface NewsMomentumRowProps {
  item: NewsMomentumItem;
}

/**
 * NewsMomentumRow — a single 22px news story row.
 *
 * Renders as an <a> when the article has a URL (the common case, 100% live),
 * otherwise a non-interactive <div> so a URL-less row still shows its headline.
 */
export function NewsMomentumRow({ item }: NewsMomentumRowProps) {
  const meta = sentimentMeta(item.sentiment);
  const pct = relevancePct(item);
  const headline = item.title ?? "Untitled article";

  // Shared inner content — identical whether the wrapper is an <a> or <div>.
  const inner = (
    <>
      {/* Sentiment dot — color + glyph encode the same bit (WCAG 1.4.1). */}
      <span aria-hidden className={cn("shrink-0 text-[8px] leading-none", meta.text)}>
        {meta.glyph}
      </span>

      {/* Headline — flex-1 + truncate absorbs the remaining width. min-w-0 on
          the flex child is what makes truncate actually clip. */}
      <span className="min-w-0 flex-1 truncate text-[10px] text-foreground">{headline}</span>

      {/* Source label — short publisher derived from the URL host. Hidden when
          absent so the column never shows an empty chip. */}
      {item.source && (
        <span className="max-w-[52px] shrink-0 truncate text-[8px] uppercase tracking-[0.04em] text-muted-foreground/70">
          {item.source}
        </span>
      )}

      {/* Relevance % — mono numerics (§15.9 hard 10px floor for data values),
          tooltip defines the metric honestly. Omitted when the server sent no
          relevance (forward-compat) rather than rendering "NaN%". */}
      {pct != null && (
        <span
          className="w-[26px] shrink-0 text-right font-mono text-[10px] tabular-nums text-muted-foreground"
          title={relevanceTitle(item)}
        >
          {pct}%
        </span>
      )}

      {/* Relative time — WHEN the story published. 9px is allowed here:
          timestamps are metadata, not data values (§15.9). */}
      <span className="w-[24px] shrink-0 text-right text-[9px] tabular-nums text-muted-foreground/70">
        {compactRelativeTime(item.published_at)}
      </span>
    </>
  );

  // 22px row, terminal density (§0). Hover affordance + focus ring for keyboard.
  const className =
    "flex h-[22px] items-center gap-1.5 px-2 transition-colors hover:bg-muted/30 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-inset focus-visible:ring-ring";

  if (item.url) {
    return (
      <a
        href={item.url}
        target="_blank"
        rel="noopener noreferrer"
        className={cn(className, "cursor-pointer")}
        title={rowTitle(item)}
        aria-label={`${headline} — ${meta.word} news${pct != null ? `, ${pct}% relevance` : ""}`}
      >
        {inner}
      </a>
    );
  }

  // No URL → non-interactive row (still shows the headline + relevance + time).
  return (
    <div className={className} title={rowTitle(item)}>
      {inner}
    </div>
  );
}
