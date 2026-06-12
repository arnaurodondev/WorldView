/**
 * components/dashboard/ai-signals/news-meta.ts — NEWS MOMENTUM display helpers
 *
 * WHY THIS EXISTS: every momentum row needs the same small derivations —
 * a sentiment dot (color + glyph), an honest relevance tooltip, and a compact
 * relative time that fits the 22px terminal row. Centralizing them keeps
 * NewsMomentumRow.tsx purely structural and gives the copy a single home.
 *
 * WHO USES IT: NewsMomentumRow.tsx, AiSignalsWidget.tsx tests
 */

import type { NewsMomentumItem } from "./types";

/**
 * sentimentMeta — semantic color class + glyph for a news sentiment.
 *
 * WHY these exact Tailwind utilities: DESIGN_SYSTEM §15.11 mandates the
 * semantic `text-positive` / `text-negative` utilities in JSX (the
 * `hsl(var(--…))` spelling is reserved for canvas/SVG). WHY a glyph as well as
 * color: color alone fails for color-blind users — ● is colored, the shape
 * (▲ up / ▼ down / ● flat) encodes direction redundantly (WCAG 1.4.1).
 */
export function sentimentMeta(sentiment: NewsMomentumItem["sentiment"]): {
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
 * relevancePct — the honest 0–100 relevance figure for the row.
 *
 * Returns null when the server sent no relevance (forward-compat / quiet feed)
 * so the caller can omit the column rather than render "NaN%".
 */
export function relevancePct(item: NewsMomentumItem): number | null {
  if (item.relevance == null || Number.isNaN(item.relevance)) return null;
  return Math.round(item.relevance * 100);
}

/**
 * relevanceTitle — the tooltip that EXPLAINS the relevance number honestly.
 *
 * WHY this copy: the screenshot-era widget showed a bare "95%" that users read
 * as a price-move prediction. This number is a composite RELEVANCE score
 * (market impact + LLM relevance + routing) — saying what it is, and that it is
 * NOT a prediction, is the honest version.
 */
export function relevanceTitle(item: NewsMomentumItem): string {
  const pct = relevancePct(item);
  if (pct == null) return "Relevance score unavailable for this article.";
  return (
    `Relevance ${pct}% — how prominent this story is right now ` +
    `(market impact + AI relevance + routing). Not a prediction of price movement.`
  );
}

/**
 * rowTitle — hover tooltip for a whole momentum row: source, sentiment and the
 * headline, so the dense 22px row reveals its detail on hover.
 */
export function rowTitle(item: NewsMomentumItem): string {
  const sentiment = sentimentMeta(item.sentiment).word;
  const src = item.source ? ` · ${item.source}` : "";
  const head = item.title ?? "Untitled article";
  return `${head}${src} (${sentiment})`;
}

/**
 * compactRelativeTime — "now" / "5m" / "3h" / "2d" for the narrow time slot.
 *
 * WHY not lib/utils formatRelativeTime: that helper returns "2h ago" /
 * "just now" — up to 8 characters, which does not fit a 22px terminal column.
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
