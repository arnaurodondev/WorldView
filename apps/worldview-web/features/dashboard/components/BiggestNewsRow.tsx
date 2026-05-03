"use client";

/**
 * features/dashboard/components/BiggestNewsRow.tsx
 *
 * Single-line callout above the gainers/losers split — surfaces the
 * highest-impact 24h article touching any member of the active watchlist.
 *
 * WHY EXTRACTED (PLAN-0059 E-5): was inline in `WatchlistMoversWidget.tsx`.
 *
 * WHY h-7 (28px): one row's worth of vertical real estate. The article
 * title truncates with a tooltip — clicking opens the article in a new tab.
 *
 * WHY noopener,noreferrer: prevents the opened tab from accessing window.opener
 * (security — the article URL is external) and omits the Referer header.
 * The exact attributes come from `newsLinkAttrs` so we honour the user's
 * "open in same tab vs new tab" preference (PLAN-0050 T-F-6-20).
 *
 * F-QA-02: defence-in-depth on the article URL. React's <a href>
 * sanitisation already blocks `javascript:` — the explicit safety check
 * here means a future imperative refactor cannot reintroduce the hole.
 */

import { Newspaper } from "lucide-react";
import {
  useNewsLinkTarget,
  newsLinkAttrs,
  isSafeNewsUrl,
} from "@/hooks/useNewsLinkTarget";
import type { WatchlistBiggestNews } from "@/types/api";

export interface BiggestNewsRowProps {
  news: WatchlistBiggestNews;
}

export function BiggestNewsRow({ news }: BiggestNewsRowProps) {
  // PLAN-0050 T-F-6-20: honour the user's tab-target preference.
  // Defaults to new-tab so existing users see no change.
  const [target] = useNewsLinkTarget();
  const linkAttrs = newsLinkAttrs(target);

  // F-QA-02 defence-in-depth: bail out on missing/unsafe URLs so the
  // component never renders a `javascript:` href. React already blocks
  // those, but the explicit guard makes the contract obvious.
  if (!news.url || !news.title || !isSafeNewsUrl(news.url)) return null;

  return (
    <a
      href={news.url}
      target={linkAttrs.target}
      rel={linkAttrs.rel}
      className="flex h-7 shrink-0 items-center gap-2 border-b border-border/30 bg-warning/5 px-2 transition-colors hover:bg-warning/10"
      aria-label={`Open biggest news: ${news.title}`}
    >
      {/* Newspaper icon + ticker chip pinned left so the title can truncate
          without pushing context off-screen. */}
      <Newspaper className="h-3 w-3 shrink-0 text-warning" aria-hidden="true" />
      {/* WHY font-semibold (was font-bold): 700-weight at 10px causes blotchy subpixel
          rendering on dark themes — 600-weight is the maximum for terminal chrome text
          at small sizes (Bloomberg density rule) */}
      {news.ticker && (
        <span className="shrink-0 font-mono text-[10px] font-semibold uppercase tabular-nums text-foreground">
          {news.ticker}
        </span>
      )}
      <span className="min-w-0 flex-1 truncate text-[11px] text-foreground" title={news.title}>
        {news.title}
      </span>
    </a>
  );
}
