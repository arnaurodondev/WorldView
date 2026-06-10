/**
 * components/instrument/intelligence/news/CompactArticleRow.tsx — T-D-02
 *
 * WHY: 28px (h-7) row for NewsColumn. Five atoms in one line:
 *   sentiment dot · time · source · headline · impact.
 * WHY 28px (not 22px): more visual weight than a metric row.
 * WHY target="_blank": external publisher URLs; preserves terminal scroll.
 */

"use client";

import { useMemo } from "react";
import { cn } from "@/lib/utils";
import type { RankedArticle } from "@/types/api";

interface CompactArticleRowProps {
  article: RankedArticle;
}

// Module-scope to avoid per-render allocation. neutral/mixed share a muted
// dot — no directional signal to encode for those values.
const SENTIMENT_DOT_CLASS: Record<NonNullable<RankedArticle["sentiment"]>, string> = {
  positive: "bg-positive",
  negative: "bg-negative",
  neutral: "bg-muted-foreground/50",
  mixed: "bg-muted-foreground/50",
};

export function CompactArticleRow({ article }: CompactArticleRowProps) {
  // useMemo: don't allocate a new onClick closure each render.
  const handleClick = useMemo(() => {
    if (!article.url) return undefined;
    const url = article.url;
    return () => window.open(url, "_blank", "noopener,noreferrer");
  }, [article.url]);

  const dotClass = article.sentiment
    ? SENTIMENT_DOT_CLASS[article.sentiment]
    : "bg-muted-foreground/30";

  // Local-time HH:MM — traders scan in their session timezone.
  const timeLabel = article.published_at
    ? new Date(article.published_at).toLocaleTimeString(undefined, {
        hour: "2-digit",
        minute: "2-digit",
        hour12: false,
      })
    : "—";

  // PRD-0026: impact_score is 0.0–1.0; spec asks for 0–100 display.
  const impactLabel =
    article.impact_score != null
      ? String(Math.round(article.impact_score * 100))
      : "—";

  return (
    <div
      onClick={handleClick}
      // Round-3 item 5 (keyboard reachability): the row already advertised
      // role="link" + tabIndex=0 but NEVER responded to the keyboard — a
      // focusable "link" that ignores Enter is an a11y trap. Enter now
      // activates exactly like click (Space is reserved for page scroll on
      // link-role elements, matching native <a> behaviour).
      onKeyDown={
        handleClick
          ? (e) => {
              if (e.key === "Enter") handleClick();
            }
          : undefined
      }
      role={article.url ? "link" : undefined}
      tabIndex={article.url ? 0 : undefined}
      className={cn(
        "h-7 flex items-center gap-2 px-3 border-b border-border/20",
        // Round-3 item 5: focus-visible ring (inset so the 28px row's ring
        // isn't clipped by the column's overflow-y-auto scroll container).
        article.url &&
          "hover:bg-muted/20 cursor-pointer focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring focus-visible:ring-inset",
      )}
    >
      <div className={cn("w-1.5 h-1.5 rounded-full flex-shrink-0", dotClass)} />
      <span className="text-[10px] font-mono text-muted-foreground w-[30px] flex-shrink-0">
        {timeLabel}
      </span>
      <span className="text-[10px] text-muted-foreground truncate w-[60px] flex-shrink-0">
        {article.source_name ?? "—"}
      </span>
      <span className="text-[11px] truncate flex-1">{article.title ?? "(untitled)"}</span>
      <span className="text-[10px] font-mono tabular-nums text-muted-foreground w-[30px] text-right flex-shrink-0">
        {impactLabel}
      </span>
    </div>
  );
}
