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
 *
 * CLASSIFIER EXPANSION (SA-2 PLAN-0088 Demo P1):
 *   Added AI, Energy, Tech buckets. These are high-value for finance traders:
 *   - AI: rapidly growing prediction market vertical; NVDA/OpenAI news catalysts
 *   - Energy: oil price, OPEC, commodity-linked equities; high institutional interest
 *   - Tech: earnings, M&A, product launches — major portfolio events
 *   Bucket priority order is: macro → politics → sports → crypto → AI → energy → tech → general
 *   WHY macro beats AI: "Fed AI policy" should read as macro (rate/fiscal context)
 *   WHY tech is last: many general-purpose market titles contain tech company names
 *   (e.g. "Will Apple release X?") — putting tech last avoids false-positives for
 *   clearly-non-tech markets that happen to mention a tech company name.
 */

// ── Category heuristic ────────────────────────────────────────────────────────

/**
 * MACRO_KEYWORDS / POLITICS_KEYWORDS / SPORTS_KEYWORDS / CRYPTO_KEYWORDS /
 * AI_KEYWORDS / ENERGY_KEYWORDS / TECH_KEYWORDS
 *
 * WHY client-side categorisation: the Polymarket API doesn't return a
 * structured `category` field consistently — it lives in tags that aren't
 * exposed by our S4 ingestion path. Title keyword matching is good enough
 * for the dashboard chip and avoids an API change. Order matters: the FIRST
 * matching set wins, so "fed bitcoin" → macro (since macro is checked
 * before crypto). Most markets only match one set, so collisions are rare.
 *
 * WHY expanded from 4 to 7 buckets: the original 4 buckets left a large
 * "general" tail. Adding AI/Energy/Tech gives traders richer signal for the
 * thematic clusters that drive the most portfolio events (tech earnings, energy
 * commodity swings, AI capex cycles).
 */
export const MACRO_KEYWORDS = [
  "fed", "rate", "inflation", "gdp", "cpi", "unemployment", "recession",
  "fomc", "payroll", "pce", "treasury", "yield", "deficit", "tariff",
  "economic", "fiscal", "monetary", "pmi", "interest rate", "fed funds",
  "central bank", "ecb", "boe", "boj", "rba", "debt ceiling",
  "federal reserve", "quantitative", "basis point", "bps",
];

export const POLITICS_KEYWORDS = [
  "election", "president", "presidential", "senate", "congress", "vote",
  "primary", "governor", "supreme court", "impeach", "legislation",
  "white house", "biden", "trump", "democrat", "republican", "executive order",
  "nato", "sanction", "un security", "g7", "g20", "oecd", "imf",
];

export const SPORTS_KEYWORDS = [
  "nba", "nfl", "mlb", "nhl", "superbowl", "super bowl", "world cup",
  "olympics", "champion", "f1", "fifa", "uefa", "stanley cup", "mvp",
  "wimbledon", "grand slam", "playoff", "series win", "tournament",
];

export const CRYPTO_KEYWORDS = [
  "bitcoin", "ethereum", "btc", "eth", "crypto", "solana", "sol", "altcoin",
  "defi", "nft", "blockchain", "coin", "token", "doge", "xrp", "ripple",
  "binance", "coinbase", "stablecoin", "web3", "layer 2",
];

/**
 * AI_KEYWORDS — Artificial-intelligence themed markets.
 * WHY separate from Tech: AI markets tend to be about model releases,
 * capabilities benchmarks, regulation, and safety — distinct from product
 * launches or earnings that drive the broader Tech bucket.
 */
export const AI_KEYWORDS = [
  "openai", "chatgpt", "gpt", "claude", "gemini", "llm", "artificial intelligence",
  "machine learning", "deep learning", "agi", "deepmind", "anthropic",
  "mistral", "llama", "sora", "ai model", "ai regulation", "ai act",
  "neural network", "robotics", "humanoid", "tesla bot", "optimus",
];

/**
 * ENERGY_KEYWORDS — Oil, gas, commodities, and energy markets.
 * WHY relevant to traders: energy price shocks drive equity sector
 * rotations (XLE, MLP, refinery names) and macro inflation expectations.
 */
export const ENERGY_KEYWORDS = [
  "oil", "crude", "opec", "brent", "wti", "natural gas", "lng",
  "pipeline", "petroleum", "gasoline", "refinery", "energy price",
  "barrel", "shale", "fracking", "renewable energy", "solar", "wind farm",
  "nuclear", "uranium", "coal", "electricity price", "carbon credit", "esg",
];

/**
 * TECH_KEYWORDS — Technology company events (earnings, M&A, products).
 * WHY last in priority: tech company names appear in many unrelated market
 * titles. Placing tech last avoids tagging a market about political news
 * involving a tech CEO as "tech" when it's really "politics".
 */
export const TECH_KEYWORDS = [
  "apple", "microsoft", "nvidia", "nvda", "amazon", "google", "alphabet",
  "meta", "tesla", "samsung", "tsmc", "intel", "amd", "qualcomm",
  "software", "semiconductor", "iphone", "android", "cloud computing",
  "aws", "azure", "datacenter", "data center", "chip", "ipo",
];

export type Category =
  | "macro"
  | "politics"
  | "sports"
  | "crypto"
  | "ai"
  | "energy"
  | "tech"
  | "general";

/**
 * categorize — derive a coarse category for the market title.
 * WHY first-match wins: the order is macro → politics → sports → crypto →
 * ai → energy → tech, putting the most finance-relevant categories first.
 * "Fed cuts rates AND BTC > 100k" → macro (correct for finance context).
 */
export function categorize(title: string): Category {
  const t = title.toLowerCase();
  if (MACRO_KEYWORDS.some((k) => t.includes(k))) return "macro";
  if (POLITICS_KEYWORDS.some((k) => t.includes(k))) return "politics";
  if (SPORTS_KEYWORDS.some((k) => t.includes(k))) return "sports";
  if (CRYPTO_KEYWORDS.some((k) => t.includes(k))) return "crypto";
  if (AI_KEYWORDS.some((k) => t.includes(k))) return "ai";
  if (ENERGY_KEYWORDS.some((k) => t.includes(k))) return "energy";
  if (TECH_KEYWORDS.some((k) => t.includes(k))) return "tech";
  return "general";
}

// ── Polymarket URL builder ──────────────────────────────────────────────────────

/**
 * MALFORMED_SLUG_TAIL — regex that detects the corrupted "numeric-tail" slugs.
 *
 * WHY this exists: ~4/525 stored slugs have a junk tail of dash-separated
 * numbers appended (e.g. `...-143-229-513-574-212-254`). These are NOT valid
 * Polymarket event slugs — navigating to `/event/{that}` 404s. The clean
 * majority (521/525) look like `will-harvey-weinstein-be-sentenced-...`.
 *
 * The pattern matches a trailing run of "-<digits>" groups, requiring at
 * LEAST three groups (`-\d+` then `(-\d+){2,}`). WHY ≥3 and not ≥1: a
 * legitimate slug can naturally end in a single number — e.g. a market about
 * "...more-than-30-years" or "...by-2024" or even "...-game-7". Requiring a
 * chain of 3+ purely-numeric segments is specific to the corruption pattern
 * and avoids false-positives on real slugs that merely contain a year/number.
 */
const MALFORMED_SLUG_TAIL = /-\d+(-\d+){2,}$/;

/**
 * buildPolymarketUrl — produce the best Polymarket link for a market row.
 *
 * WHY a single shared helper: the URL was previously constructed in THREE
 * places (the gateway transform, the dashboard widget, the /prediction-markets
 * page), each with its own subtly-different fallback logic. The widget + page
 * even hardcoded a title-search URL because the gateway set `url: ""`. That
 * divergence is the "wrong links" bug — every row went to a generic text
 * search instead of the specific market. Centralising here guarantees one
 * behaviour everywhere.
 *
 * RETURN VALUE:
 *   - A canonical deep link `https://polymarket.com/event/{slug}` when `slug`
 *     is a clean, non-empty slug.
 *   - The title-search fallback `https://polymarket.com/markets?_q={title}`
 *     when the slug is null/empty/whitespace OR matches the malformed
 *     numeric-tail pattern above. The search page always resolves to a usable
 *     results list, so it is a safe degraded experience.
 *
 * WHY `/event/` (and NOT `/market/`): Polymarket serves two canonical paths.
 * `/event/{slug}` is the grouped/standard page for the markets we ingest from
 * the Gamma API — it is the page a human lands on from Polymarket's own UI and
 * the one that resolves for our slugs. `/market/{slug}` is the single-binary
 * sub-route and does NOT match our stored slugs, so using it would 404. We
 * deliberately use `/event/` for the deep link.
 */
export function buildPolymarketUrl(
  slug: string | null | undefined,
  title: string,
): string {
  // WHY trim first: a slug that is whitespace-only is effectively empty and
  // must take the search fallback, not produce `/event/%20`.
  const cleanSlug = (slug ?? "").trim();

  // The search fallback. WHY encodeURIComponent: titles contain spaces, `?`,
  // `%`, etc. which would otherwise break the query string. `title` may be ""
  // (the gateway sets description "" but title is always present) — an empty
  // search still lands on Polymarket's market list rather than a broken URL.
  const searchUrl = `https://polymarket.com/markets?_q=${encodeURIComponent(title)}`;

  // Empty / whitespace slug → search fallback.
  if (cleanSlug.length === 0) return searchUrl;
  // Malformed numeric-tail slug → search fallback (would 404 on /event/).
  if (MALFORMED_SLUG_TAIL.test(cleanSlug)) return searchUrl;

  // Clean slug → canonical deep link.
  return `https://polymarket.com/event/${cleanSlug}`;
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
