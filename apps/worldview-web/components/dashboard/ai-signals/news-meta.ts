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
 * SortMode — how the user wants the momentum feed RANKED.
 *
 *  - "top"      = the server's own surge ranking (the default; what S6 returns).
 *                 We keep this as the landing view because the backend already
 *                 ranks by an honest composite surge metric — the user only
 *                 reaches for the explicit increase/decrease modes when they want
 *                 to scan one direction.
 *  - "increase" = BIGGEST INCREASE — most positive momentum first
 *                 (delta_pct DESCENDING: ↑500%, ↑200%, ↑40%, … , ↓60%).
 *  - "decrease" = BIGGEST DECREASE — most negative / declining momentum first
 *                 (delta_pct ASCENDING: ↓60%, ↓10%, flat, … , ↑500%).
 *
 * WHY delta_pct (not delta): delta_pct is the RELATIVE surge (already floored by
 * the server so it is finite), which is the apples-to-apples velocity reading the
 * trend column shows. Ranking by it keeps the visible ↑/↓ % consistent with the
 * order.
 */
export type SortMode = "top" | "increase" | "decrease";

/**
 * sortMomentumItems — return a NEW array of the items ranked by the chosen mode.
 *
 * WHY pure + non-mutating: the source array comes from TanStack Query's cache.
 * Mutating it in place (Array.prototype.sort sorts in place) would corrupt the
 * cached payload and make the order depend on render history. We copy first
 * ([...items]) so each render derives a fresh, deterministic ordering.
 *
 * SORT SEMANTICS (the whole point of this control):
 *  - "increase": delta_pct DESCENDING  → most positive momentum at the top.
 *  - "decrease": delta_pct ASCENDING   → most negative momentum at the top.
 *  - "top":      untouched server order (already ranked by surge) — returned as a
 *                shallow copy for a consistent contract (callers can treat the
 *                result as freshly owned).
 *
 * NULL/0 SAFETY: a missing delta_pct is coerced to 0 (`?? 0`) so a partial row
 * (forward-compat: an older S9 might omit the field) sorts as "flat" rather than
 * throwing or sorting as NaN (which would scatter rows unpredictably).
 *
 * TIE-BREAKS (so the order is STABLE and meaningful when delta_pct ties — common
 * for new-coverage rows that all read ↑100%):
 *   1. higher current article `count` first (more coverage = more notable);
 *   2. then ticker A→Z (a deterministic, human-readable final tiebreak so the
 *      list never reshuffles between renders for equal rows).
 */
export function sortMomentumItems(items: NewsMomentumItem[], mode: SortMode): NewsMomentumItem[] {
  // "top" = trust the server's surge ranking; just hand back an owned copy.
  if (mode === "top") return [...items];

  // Direction multiplier: increase ranks high→low (desc), decrease low→high (asc).
  const direction = mode === "increase" ? -1 : 1;

  return [...items].sort((a, b) => {
    const aPct = a.delta_pct ?? 0; // null/undefined delta_pct → treat as flat (0)
    const bPct = b.delta_pct ?? 0;
    if (aPct !== bPct) {
      // direction === -1 → descending (increase); direction === 1 → ascending.
      return (aPct - bPct) * direction;
    }

    // Tie-break 1: more current articles first (higher coverage = more notable).
    const aCount = a.count ?? 0;
    const bCount = b.count ?? 0;
    if (aCount !== bCount) return bCount - aCount;

    // Tie-break 2: ticker A→Z — a deterministic, render-stable final ordering.
    return (a.ticker ?? "").localeCompare(b.ticker ?? "");
  });
}

/**
 * trendMeta — the MOMENTUM signal: arrow glyph + semantic color + a compact
 * label for a row's count change vs the prior window.
 *
 * WHY this is the headline number (not relevance): the feed is ranked by surge,
 * so the trend is what makes a row notable. We always show a PERCENTAGE (e.g.
 * ↑200%) — the financial convention used by every other mover widget in the
 * dashboard. The label is capped at 999% so it never overflows the fixed ~w-[44px]
 * slot even for explosive new-coverage tickers. The raw article counts are still
 * available in the hover tooltip (trendTitle / rowTitle) so no absolute info is
 * lost by switching to % here.
 *
 * NEW-coverage rows (is_new === true, i.e. prior_count === 0): there is NO baseline,
 * so a percentage is undefined. The server sends is_new + delta_pct=0.0; we render a
 * "NEW" badge instead of a fabricated number. (Previously the server floored the
 * denominator at 1, turning 0→N into "N*100%" — so during a news-ingestion gap, when
 * the prior window is empty for EVERY row, the whole widget read as ↑700%–↑1400%.)
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
  const pct = item.delta_pct ?? 0;

  // New coverage: no prior-window baseline → show "NEW", not a percentage.
  if (item.is_new) {
    return { arrow: "↑", text: "text-positive", label: "NEW", word: "new coverage" };
  }

  if (delta > 0) {
    // Always emit a percentage — consistent with every other mover widget.
    // Cap at 999% so the label never overflows the fixed ~w-[44px] slot.
    // NOTE: do NOT switch to "+N" when prior===0 — that breaks unit consistency
    // (absolute count vs percentage in the same widget). Raw counts live in the
    // tooltip (trendTitle / rowTitle) so the absolute info isn't lost.
    const label = `↑${Math.min(Math.round(pct), 999)}%`;
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
