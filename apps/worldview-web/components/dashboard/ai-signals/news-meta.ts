/**
 * components/dashboard/ai-signals/news-meta.ts — NEWS MOMENTUM display helpers
 *
 * WHY THIS EXISTS: every momentum row needs the same small derivations — the
 * trend arrow + color (the surge, the whole point), a sentiment dot for the
 * headline, an honest relevance tooltip, and a compact relative time that fits
 * the 22px terminal row. Centralizing them keeps NewsMomentumRow.tsx purely
 * structural and gives the copy a single home.
 *
 * WHO USES IT: NewsMomentumRow.tsx, AiSignalsWidget.tsx tests
 */

import type { NewsMomentumItem } from "./types";

/**
 * trendMeta — the MOMENTUM signal: arrow glyph + semantic color + a compact
 * label for a row's count change vs the prior window.
 *
 * WHY this is the headline number (not relevance): the feed is ranked by surge,
 * so the trend is what makes a row notable. We show the signed delta_pct when a
 * baseline exists (e.g. ↑200%); when prior_count was 0 the percentage is
 * unbounded-but-finite (server floors the denominator at 1), so we prefer the
 * absolute "+N" reading ("new" coverage) which is more honest than "↑400%".
 *
 * Color: §15.11 semantic utilities — text-positive (rising), text-negative
 * (falling), muted (flat). Arrow + color encode the same bit (WCAG 1.4.1) so
 * color-blind users still read direction.
 */
export function trendMeta(item: NewsMomentumItem): {
  arrow: string;
  text: string;
  label: string;
  word: string;
} {
  const delta = item.delta ?? 0;
  const prior = item.prior_count ?? 0;
  const pct = item.delta_pct ?? 0;

  if (delta > 0) {
    // New coverage (no prior baseline) reads better as "+N new" than a giant %.
    const label = prior === 0 ? `+${delta}` : `↑${Math.round(pct)}%`;
    return { arrow: "↑", text: "text-positive", label, word: "rising" };
  }
  if (delta < 0) {
    return { arrow: "↓", text: "text-negative", label: `↓${Math.abs(Math.round(pct))}%`, word: "falling" };
  }
  // Flat: same coverage as the prior window.
  return { arrow: "→", text: "text-muted-foreground", label: "flat", word: "flat" };
}

/**
 * sentimentMeta — semantic color class + glyph for the headline's sentiment.
 *
 * WHY a glyph as well as color: color alone fails for color-blind users (WCAG
 * 1.4.1); the shape (▲ up / ▼ down / ● flat) encodes direction redundantly.
 */
export function sentimentMeta(sentiment: string | null | undefined): {
  text: string;
  glyph: string;
  word: string;
} {
  switch (sentiment) {
    case "positive":
      return { text: "text-positive", glyph: "▲", word: "positive" };
    case "negative":
      return { text: "text-negative", glyph: "▼", word: "negative" };
    default:
      // neutral / mixed / null all land here — a muted flat dot.
      return { text: "text-muted-foreground", glyph: "●", word: "neutral" };
  }
}

/**
 * countLabel — the article-count reading for the row, e.g. "12 articles".
 *
 * Singular/plural aware; returns "" when count is missing so the caller can omit
 * the column rather than render "null articles".
 */
export function countLabel(item: NewsMomentumItem): string {
  const c = item.count;
  if (c == null || Number.isNaN(c)) return "";
  return `${c} ${c === 1 ? "article" : "articles"}`;
}

/**
 * relevancePct — the honest 0–100 relevance figure for the entity's headline.
 *
 * Returns null when the server sent no relevance so the caller can omit it.
 */
export function relevancePct(item: NewsMomentumItem): number | null {
  const r = item.top_article?.relevance;
  if (r == null || Number.isNaN(r)) return null;
  return Math.round(r * 100);
}

/**
 * trendTitle — tooltip EXPLAINING the momentum number honestly. The window
 * length is interpolated so the user knows what "prior" means.
 */
export function trendTitle(item: NewsMomentumItem, windowLabel: string): string {
  const cur = item.count ?? 0;
  const prior = item.prior_count ?? 0;
  const t = trendMeta(item);
  return (
    `${cur} article${cur === 1 ? "" : "s"} in the last ${windowLabel}, ` +
    `vs ${prior} in the prior ${windowLabel} (${t.word}). ` +
    `Ranked by surge in news coverage — not a prediction of price movement.`
  );
}

/**
 * rowTitle — hover tooltip for the whole row: ticker, name, trend and the
 * top headline, so the dense 22px row reveals its detail on hover.
 */
export function rowTitle(item: NewsMomentumItem, windowLabel: string): string {
  const sym = item.ticker ?? "?";
  const name = item.name ?? "";
  const head = item.top_article?.title;
  const headPart = head ? ` — "${head}"` : "";
  return `${sym} ${name} · ${trendMeta(item).label} (${countLabel(item)} in ${windowLabel})${headPart}`;
}

/**
 * compactRelativeTime — "now" / "5m" / "3h" / "2d" for the narrow time slot.
 *
 * WHY not lib/utils formatRelativeTime: that helper returns up to 8 characters
 * ("2h ago" / "just now"), which does not fit a 22px terminal column.
 */
export function compactRelativeTime(isoString: string | null | undefined): string {
  if (!isoString) return "—";
  const then = new Date(isoString).getTime();
  // NaN guards against malformed timestamps from a degraded upstream.
  if (Number.isNaN(then)) return "—";
  const diffSeconds = Math.floor((Date.now() - then) / 1000);
  if (diffSeconds < 60) return "now";
  if (diffSeconds < 3600) return `${Math.floor(diffSeconds / 60)}m`;
  if (diffSeconds < 86400) return `${Math.floor(diffSeconds / 3600)}h`;
  return `${Math.floor(diffSeconds / 86400)}d`;
}
