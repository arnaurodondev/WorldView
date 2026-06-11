/**
 * components/dashboard/ai-signals/signal-meta.ts — display metadata helpers
 *
 * WHY THIS EXISTS: every signal row needs the same three derivations —
 * direction colors, a human chip label, and an honest confidence tooltip.
 * Centralizing them keeps SignalGroupRow.tsx purely structural and gives the
 * copy a single home (the old widget scattered ternaries through JSX).
 *
 * WHO USES IT: SignalGroupRow.tsx, AiSignalsWidget.tsx tests
 */

import type { EnrichedAiSignal } from "./types";

/**
 * directionMeta — semantic color classes + glyph for a signal direction.
 *
 * WHY these exact Tailwind utilities: DESIGN_SYSTEM §15.11 mandates the
 * semantic `text-positive` / `bg-positive` utilities in JSX (the
 * `hsl(var(--…))` arbitrary-value spelling is reserved for canvas/SVG).
 * `--positive` = teal-green, `--negative` = muted red — the TradingView
 * up/down convention used across the whole app.
 *
 * WHY a glyph as well as color: color alone fails for color-blind users;
 * ▲ / ▼ / ▪ encode direction redundantly (WCAG 1.4.1 "use of color").
 */
export function directionMeta(label: EnrichedAiSignal["label"]): {
  text: string;
  bg: string;
  glyph: string;
  word: string;
} {
  switch (label) {
    case "POSITIVE":
      return { text: "text-positive", bg: "bg-positive", glyph: "▲", word: "bullish" };
    case "NEGATIVE":
      return { text: "text-negative", bg: "bg-negative", glyph: "▼", word: "bearish" };
    default:
      return {
        text: "text-muted-foreground",
        bg: "bg-muted-foreground/50",
        glyph: "▪",
        word: "neutral",
      };
  }
}

/**
 * chipLabel — text for the signal-type chip.
 *
 * The enriched payload humanizes the enum server-side (signal_type_label);
 * a LEGACY payload (older S9) has neither field, so we degrade to the
 * generic word "Signal" rather than hiding the chip — layout stability
 * beats conditional columns at 22px row height.
 */
export function chipLabel(signal: EnrichedAiSignal): string {
  return signal.signal_type_label ?? signal.signal_type ?? "Signal";
}

/**
 * confidenceTitle — the tooltip that finally EXPLAINS the percentage.
 *
 * WHY this copy: the screenshot-era widget showed bare "95%" values that
 * users (reasonably) read as a price-move prediction. The number is actually
 * the extraction model's confidence that the event was stated in the article.
 * Saying what it is — and explicitly what it is NOT — is the honest version.
 */
export function confidenceTitle(signal: EnrichedAiSignal): string {
  const pct = Math.round(signal.score * 100);
  return (
    `Extraction confidence ${pct}% — how certain the AI is that this event ` +
    `was stated in the article. Not a prediction of price movement.`
  );
}

/**
 * rowTitle — hover tooltip for a whole signal row: type, direction and the
 * triggering headline, so the dense 22px row reveals its evidence on hover.
 */
export function rowTitle(signal: EnrichedAiSignal): string {
  const direction = directionMeta(signal.label).word;
  const head = `${chipLabel(signal)} (${direction})`;
  return signal.article_title ? `${head} — ${signal.article_title}` : head;
}

/**
 * compactRelativeTime — "now" / "5m" / "3h" / "2d" for the 26px time slot.
 *
 * WHY not lib/utils formatRelativeTime: that helper returns "2h ago" /
 * "just now" — up to 8 characters, which does not fit a 22px-row terminal
 * column. RecentAlerts solved this with a private relativeTime() helper we
 * cannot import (other workstream's file), so the compact variant lives here.
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
