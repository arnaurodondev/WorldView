/**
 * lib/prediction-markets.ts — Shared prediction-market utilities
 *
 * WHY THIS EXISTS: The categorize() and formatCountdown() functions were
 * originally inline in PredictionMarketsWidget.tsx. Extracting them here
 * (PLAN-0068 C-2-02) creates a single source of truth so the widget and
 * the /prediction-markets page share the same keyword lists and logic,
 * preventing the silent divergence that would occur if both copied the
 * arrays independently.
 *
 * WHO USES IT: PredictionMarketsWidget.tsx (dashboard chip + countdown),
 *              app/(app)/prediction-markets/page.tsx (category pills).
 */

// ── Category heuristic ────────────────────────────────────────────────────────

/**
 * MACRO_KEYWORDS / POLITICS_KEYWORDS / SPORTS_KEYWORDS / CRYPTO_KEYWORDS
 *
 * WHY client-side categorisation: the Polymarket API doesn't return a
 * structured `category` field consistently — it lives in tags that aren't
 * exposed by our S4 ingestion path. Title keyword matching is good enough
 * for the dashboard chip and avoids an API change. Order matters: the FIRST
 * matching set wins, so "fed bitcoin" → macro (since macro is checked
 * before crypto). Most markets only match one set, so collisions are rare.
 *
 * WHY four buckets + "general" default: covers the dominant Polymarket
 * verticals that finance traders care about. Anything else falls into
 * "general" — neutral chip so the trader can still skim the row.
 */
export const MACRO_KEYWORDS = [
  "fed", "rate", "inflation", "gdp", "cpi", "unemployment", "recession",
  "fomc", "payroll", "pce", "treasury", "yield", "deficit", "tariff",
  "economic", "fiscal", "monetary", "pmi",
];

export const POLITICS_KEYWORDS = [
  "election", "president", "presidential", "senate", "congress", "vote",
  "primary", "governor", "supreme court", "impeach",
];

export const SPORTS_KEYWORDS = [
  "nba", "nfl", "mlb", "nhl", "superbowl", "super bowl", "world cup",
  "olympics", "champion", "f1", "fifa", "uefa",
];

export const CRYPTO_KEYWORDS = [
  "bitcoin", "ethereum", "btc", "eth", "crypto", "solana", "sol", "altcoin",
];

export type Category = "macro" | "politics" | "sports" | "crypto" | "general";

/**
 * categorize — derive a coarse category for the market title.
 * WHY first-match wins: the order is macro → politics → sports → crypto,
 * putting the most finance-relevant categories first so a "Fed cuts rates
 * AND BTC > 100k" market is tagged macro (right call for a finance dashboard).
 */
export function categorize(title: string): Category {
  const t = title.toLowerCase();
  if (MACRO_KEYWORDS.some((k) => t.includes(k))) return "macro";
  if (POLITICS_KEYWORDS.some((k) => t.includes(k))) return "politics";
  if (SPORTS_KEYWORDS.some((k) => t.includes(k))) return "sports";
  if (CRYPTO_KEYWORDS.some((k) => t.includes(k))) return "crypto";
  return "general";
}

// ── Countdown helper ──────────────────────────────────────────────────────────

/**
 * formatCountdown — convert a close-time ISO string to a relative label.
 *
 * WHY hand-rolled (not date-fns): keeping new deps to zero (project rule).
 * The four-state output (closed / closes today / closes in Nd / —) is small
 * enough that the formatting logic is clearer inline than via a library.
 *
 * Output:
 *   - null close-time    → "—"  (no resolution date known)
 *   - close < now        → "closed"
 *   - same calendar UTC day → "closes today"
 *   - else               → "closes in Nd"
 *
 * WHY UTC day comparison: avoids timezone surprises where a NY trader sees
 * a market labelled "closes in 1d" while a London trader sees "today" for
 * the same row. The trade-off: a market closing 03:00 UTC tomorrow shows
 * "closes in 1d" to a NY trader at 23:00 ET (their "today" is the close
 * day local). Acceptable since the precise close time is in the row title.
 */
export function formatCountdown(closeIso: string | null | undefined): string {
  if (!closeIso) return "—";
  const close = new Date(closeIso);
  if (Number.isNaN(close.getTime())) return "—";
  const now = new Date();
  if (close.getTime() <= now.getTime()) return "closed";

  // Compare UTC calendar day for "today" check.
  const sameUtcDay =
    close.getUTCFullYear() === now.getUTCFullYear() &&
    close.getUTCMonth() === now.getUTCMonth() &&
    close.getUTCDate() === now.getUTCDate();
  if (sameUtcDay) return "closes today";

  // Round UP days remaining: a market closing in 25 hours should read
  // "closes in 2d", not "1d" — traders need the upper bound to plan around.
  const msPerDay = 24 * 60 * 60 * 1000;
  const days = Math.ceil((close.getTime() - now.getTime()) / msPerDay);
  return `closes in ${days}d`;
}
