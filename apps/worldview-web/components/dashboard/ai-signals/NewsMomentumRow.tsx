/**
 * components/dashboard/ai-signals/NewsMomentumRow.tsx — one news-momentum row
 *
 * WHY THIS EXISTS: this component renders ONE row per surging ENTITY — the unit
 * the user cares about ("which ticker is gaining news attention right now?"):
 *
 *   NVDA  Nvidia            ↑200%  Nvidia Breaks Below $200 …        4m
 *   └─ row click → /instruments/NVDA      headline click → the article
 *
 *  - ticker (mono) — the tradeable symbol; the whole row navigates to it.
 *  - name (truncate) — the resolved canonical name (never a UUID stub).
 *  - trend (↑/↓ arrow + Δ%, semantic color) — the MOMENTUM, the whole point.
 *  - sentiment dot — direction of the entity's top headline.
 *  - headline — the most relevant recent story; clicking it opens the publisher
 *    (and stops row navigation so the two click targets don't fight).
 *  - count + relative time — how many articles, and how fresh.
 *
 * WHY two click targets: the row's PRIMARY action is "show me this entity"
 * (→ /instruments/[ticker]); the headline is a SECONDARY shortcut to read the
 * specific story. The headline anchor calls stopPropagation so a headline click
 * opens the article without also triggering the row's navigation.
 *
 * WHO USES IT: AiSignalsWidget.tsx (one per NewsMomentumItem)
 * DESIGN REFERENCE: DESIGN_SYSTEM §0 terminal density (22px rows), §15.9 mono
 * numerics, §15.11 semantic color utilities.
 */

"use client";
// WHY "use client": uses useRouter for row navigation + interactive handlers.

import { useRouter } from "next/navigation";

import { cn } from "@/lib/utils";

import {
  compactRelativeTime,
  countLabel,
  relevancePct,
  rowTitle,
  sentimentMeta,
  trendMeta,
  trendTitle,
} from "./news-meta";
import type { NewsMomentumItem } from "./types";

interface NewsMomentumRowProps {
  item: NewsMomentumItem;
  /** Human label for the active window ("24H" / "3D" / "1W") — for tooltips. */
  windowLabel: string;
}

/**
 * NewsMomentumRow — a single 22px entity-momentum row.
 *
 * Renders as an interactive row (button semantics) when the entity has a ticker
 * to navigate to (the common case — S6 only emits ticker'd entities), otherwise
 * a non-interactive div so a ticker-less row still shows its data.
 */
export function NewsMomentumRow({ item, windowLabel }: NewsMomentumRowProps) {
  const router = useRouter();

  const trend = trendMeta(item);
  const headline = item.top_article?.title;
  const headlineUrl = item.top_article?.url;
  const sentiment = sentimentMeta(item.top_article?.sentiment);
  const pct = relevancePct(item);
  const ticker = item.ticker ?? null;
  const navTarget = ticker ? `/instruments/${ticker}` : null;

  // Shared inner content — identical whether the wrapper navigates or not.
  const inner = (
    <>
      {/* Ticker — mono, the navigation target. Fixed width so names align. */}
      <span className="w-[48px] shrink-0 truncate font-mono text-[10px] font-medium tabular-nums text-foreground">
        {ticker ?? "—"}
      </span>

      {/* Name — truncates to absorb slack. min-w-0 makes truncate actually clip. */}
      <span className="min-w-0 flex-1 truncate text-[10px] text-muted-foreground">{item.name ?? ""}</span>

      {/* Trend — the MOMENTUM signal: arrow+Δ%, semantic color. Tooltip explains
          it honestly (count now vs prior window; not a price prediction). */}
      <span
        className={cn("w-[44px] shrink-0 text-right font-mono text-[10px] tabular-nums", trend.text)}
        title={trendTitle(item, windowLabel)}
      >
        {trend.label}
      </span>

      {/* Sentiment dot for the headline — color + glyph (WCAG 1.4.1). */}
      <span aria-hidden className={cn("shrink-0 text-[8px] leading-none", sentiment.text)}>
        {sentiment.glyph}
      </span>

      {/* Headline — the most relevant recent story. As an <a> when a URL exists
          (opens the publisher); stopPropagation so it doesn't also navigate the
          row. Truncates within a bounded width so the time column stays put. */}
      {headline ? (
        headlineUrl ? (
          <a
            href={headlineUrl}
            target="_blank"
            rel="noopener noreferrer"
            onClick={(e) => e.stopPropagation()}
            className="min-w-0 max-w-[40%] truncate text-[10px] text-foreground/80 hover:text-foreground hover:underline"
            title={pct != null ? `${headline} (${pct}% relevance)` : headline}
          >
            {headline}
          </a>
        ) : (
          <span className="min-w-0 max-w-[40%] truncate text-[10px] text-foreground/80" title={headline}>
            {headline}
          </span>
        )
      ) : (
        // No headline yet (rare) — keep the column slot so the row aligns.
        <span className="min-w-0 max-w-[40%] truncate text-[10px] text-muted-foreground/50">—</span>
      )}

      {/* Relative time — WHEN the top story published. 9px is allowed for
          metadata timestamps (§15.9). */}
      <span className="w-[24px] shrink-0 text-right text-[9px] tabular-nums text-muted-foreground/70">
        {compactRelativeTime(item.top_article?.published_at)}
      </span>
    </>
  );

  // 22px row, terminal density (§0). Hover affordance + focus ring for keyboard.
  const className =
    "flex h-[22px] w-full items-center gap-1.5 px-2 text-left transition-colors hover:bg-muted/30 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-inset focus-visible:ring-ring";

  if (navTarget) {
    return (
      <button
        type="button"
        onClick={() => router.push(navTarget)}
        className={cn(className, "cursor-pointer")}
        title={rowTitle(item, windowLabel)}
        aria-label={`${ticker} ${item.name ?? ""} — ${trend.word}, ${countLabel(item)}. Open instrument page.`}
      >
        {inner}
      </button>
    );
  }

  // No ticker → non-interactive row (still shows the data).
  return (
    <div className={className} title={rowTitle(item, windowLabel)}>
      {inner}
    </div>
  );
}
