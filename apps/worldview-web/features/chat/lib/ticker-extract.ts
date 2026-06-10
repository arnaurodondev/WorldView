/**
 * features/chat/lib/ticker-extract.ts — Pure ticker-mention extractor for the
 * chat conversation log.
 *
 * WHY THIS EXISTS (Round 2 Enhancement — Chat surface):
 * Three different chat surfaces previously each carried their own inline
 * ticker regex (the page's composer quick-chips, ChatContextRail's
 * $TICKER scan, and ChatContextRail's **BOLD** scan). Each had slightly
 * different rules and slightly different blocklists, so the same thread
 * could show different "detected entities" in different places. This module
 * is the single, well-tested source of truth the rail (and future surfaces)
 * import.
 *
 * EXTRACTION RULES (per Round-2 task spec):
 *   1. `$TICKER` — a `$` followed by 1–5 uppercase letters, word-bounded.
 *      ALWAYS counts. The `$` prefix is an explicit human intent signal
 *      ("$F" means Ford, not the preposition), so it bypasses the blocklist
 *      and the 2-char minimum that bare tokens must satisfy.
 *   2. Bare `TICKER` — 2–5 uppercase letters, word-bounded, in ANY message
 *      (user or assistant). Bare tokens are inherently ambiguous ("CEO",
 *      "GDP", "VERY" all match the shape), so they must pass the
 *      NOISE_BLOCKLIST below. Single bare letters ("A", "I") are never
 *      accepted — the false-positive rate on English text is near 100%.
 *
 * WHY NO DIGITS IN EITHER PATTERN: real-world primary-listing tickers the
 * platform tracks are alphabetic; allowing digits would match "Q1", "10K",
 * "8K" etc. Quarters (Q1–Q4) therefore can never match by construction —
 * they appear in the blocklist anyway as documentation of intent.
 *
 * WHY A GENEROUS BLOCKLIST: per the task spec, false positives are WORSE
 * than misses here — every accepted ticker renders a mini-card in the
 * context rail that fires real network requests (instrument search +
 * company overview). A miss costs the analyst one `$` prefix keystroke to
 * recover; a false positive costs network round-trips and visual noise.
 * Note the second safety net: the rail only RENDERS a card when the ticker
 * actually resolves via the instrument-search endpoint, so blocklist
 * escapes degrade to a wasted request, never to a phantom card.
 *
 * ORDERING CONTRACT: results are deduped and ordered MOST-RECENT-FIRST
 * (tickers mentioned in the newest message rank first). This is what lets
 * the rail cap at the "8 most recent" with an overflow count — as the
 * conversation moves on to new names, old ones fall off the end.
 *
 * PURITY: no React, no fetch, no Date — fully deterministic so the
 * table-driven Vitest suite can pin every rule.
 */

// ── Patterns ──────────────────────────────────────────────────────────────────

/**
 * `$TICKER` — explicit-intent pattern. 1–5 uppercase letters after `$`.
 * `(?![A-Za-z])` (not `\b`) closes the token: `\b` would still match the
 * "AAPL" prefix inside `$AAPLX` overflow… it wouldn't, but the negative
 * lookahead documents the intent explicitly: the letters must END at a
 * non-letter. `$AAPL5` is rejected too? No — digits after the letters do
 * not break the match (`$BRK` inside `$BRK2` is unlikely in practice and
 * harmless given the resolve-before-render safety net).
 *
 * WHY lowercase is NOT matched: "$cash" in casual writing is slang, not a
 * ticker reference; requiring uppercase mirrors how analysts actually type
 * symbols and keeps the rule predictable.
 */
const DOLLAR_TICKER_RE = /\$([A-Z]{1,5})(?![A-Za-z])/g;

/**
 * Bare `TICKER` — 2–5 uppercase letters with word boundaries on both sides.
 * `\b` correctly rejects tokens glued to digits ("10K", "AAPL5") because
 * digits are word characters (no boundary forms between `L` and `5`), and
 * correctly accepts tokens wrapped in punctuation ("(NVDA)", "**AMD**",
 * "TSM?") because punctuation is a non-word character.
 */
const BARE_TICKER_RE = /\b([A-Z]{2,5})\b/g;

// ── Noise blocklist ───────────────────────────────────────────────────────────

/**
 * Uppercase tokens that match the bare-ticker shape but are (almost) never
 * intended as ticker references in a finance conversation. Deliberately
 * GENEROUS — see file header for the false-positive > miss rationale.
 *
 * Some entries collide with real tickers (e.g. "ALL" = Allstate, "KEY" =
 * KeyCorp, "IT" = Gartner). That is accepted by design: the analyst can
 * always force detection with the `$` prefix ("$ALL"), which bypasses this
 * list entirely.
 *
 * Grouped for maintainability; the Set flattens them at module load.
 */
const NOISE_TOKENS: readonly string[] = [
  // ── Corporate roles / org chrome ──
  "CEO", "CFO", "COO", "CTO", "CIO", "CMO", "CHRO", "VP", "SVP", "EVP",
  "HR", "IR", "PR", "RD", "BOD", "LLC", "INC", "CORP", "LTD", "PLC", "CO",
  // ── Finance & accounting abbreviations ──
  "EPS", "PE", "PEG", "PS", "PB", "EV", "TTM", "YOY", "QOQ", "MOM", "FY",
  "GAAP", "FCF", "ROE", "ROA", "ROI", "ROIC", "IRR", "NPV", "DCF", "WACC",
  "CAGR", "CAPEX", "OPEX", "EBIT", "COGS", "SGA", "AUM", "NAV", "ATH",
  "ATL", "YTD", "MTD", "QTD", "BPS", "BP", "OTC", "ADR", "REIT", "SPAC",
  "ETF", "ETN", "IPO", "ESG", "DD", "PT", "EOD", "AH", "PM", "AM",
  // ── Institutions / regulators / macro ──
  "SEC", "FED", "FOMC", "ECB", "BOE", "BOJ", "IMF", "WTO", "OPEC", "GDP",
  "CPI", "PPI", "PCE", "PMI", "ISM", "NFP", "FDIC", "IRS", "DOJ", "FTC",
  "FDA", "EPA", "DOE", "NATO", "UN", "WHO", "CDC",
  // ── Exchanges / indices ──
  "NYSE", "AMEX", "CBOE", "LSE", "TSX", "HKEX", "SPX", "NDX", "DJIA",
  "DJI", "VIX", "RUT", "FTSE", "DAX", "CAC", "HSI", "NI",
  // NOTE: "NASDAQ" is 6 letters — can't match the 2–5 pattern; listed
  // nowhere because it's unmatchable by construction.
  // ── Currencies / regions ──
  "USD", "EUR", "GBP", "JPY", "CNY", "CHF", "CAD", "AUD", "NZD", "HKD",
  "KRW", "INR", "BRL", "MXN", "RUB", "FX", "US", "USA", "UK", "EU", "EMEA",
  "APAC", "LATAM", "NA", "NYC", "DC", "LA", "SF",
  // ── Tech / general abbreviations common in LLM answers ──
  "AI", "ML", "API", "APIS", "GPU", "CPU", "TPU", "SAAS", "PAAS", "IAAS",
  "IOT", "AR", "VR", "EVS", "URL", "HTTP", "HTTPS", "SQL", "AWS", "GCP",
  "LLM", "LLMS", "NLP", "OS", "PC", "TV", "UI", "UX", "ID", "OEM", "B2B",
  "B2C", "KPI", "OKR", "MVP", "POC", "GA", "EOL", "FAQ", "FYI", "ASAP",
  "IMO", "TLDR", "TBD", "ETA", "EST", "PST", "GMT", "UTC", "CET",
  // ── Quarters / periods (digits make these unmatchable; kept as intent docs) ──
  "Q1", "Q2", "Q3", "Q4", "H1", "H2",
  // ── Common English words analysts type in caps for emphasis ──
  "A", "I", "AN", "THE", "AND", "OR", "NOT", "NOR", "BUT", "FOR", "OF",
  "IN", "ON", "AT", "TO", "BY", "BE", "DO", "IF", "UP", "NO", "YES", "VS",
  "VIA", "PER", "IS", "IT", "AS", "WE", "HE", "SO", "MY", "ME", "OK",
  "ALL", "ANY", "ARE", "WAS", "WERE", "HAS", "HAD", "HAVE", "WILL", "CAN",
  "MAY", "NOW", "NEW", "OLD", "TOP", "LOW", "HIGH", "BIG", "OUT", "OVER",
  "UNDER", "MORE", "MOST", "LESS", "LEAST", "BEST", "WORST", "GOOD", "BAD",
  "WELL", "VERY", "MUCH", "MANY", "SOME", "NONE", "BOTH", "EACH", "WHAT",
  "WHEN", "WHY", "HOW", "WHO", "WHOM", "THIS", "THAT", "THESE", "THOSE",
  "ALSO", "JUST", "ONLY", "EVEN", "STILL", "YET", "THAN", "THEN", "THEM",
  "THEY", "THEIR", "FROM", "WITH", "INTO", "ONTO", "ABOUT", "AFTER",
  "SINCE", "WHILE", "WHERE", "HERE", "THERE", "TODAY", "NOTE", "ETC",
  "EG", "IE", "RE", "OKAY", "PLS", "THX", "BUY", "SELL", "HOLD",
  "LONG", "SHORT", "CALL", "PUT", "CALLS", "PUTS", "BULL", "BEAR", "RISK",
  "NEWS", "STOCK", "BOND", "BONDS", "CASH", "DEBT", "LOSS", "GAIN", "BEAT",
  "MISS", "GUIDE", "PEERS", "PEER", "PRICE", "VALUE", "CHART", "TREND",
  "DOWN", "FLAT", "OPEN", "CLOSE", "RANGE", "LEVEL", "SHARE", "TOTAL",
  "YEAR", "WEEK", "DAY", "MONTH", "DATE", "TIME", "RATE", "RATES", "YIELD",
];

/**
 * Exported as a Set so the table-driven tests can assert membership of the
 * exact tokens the spec calls out (CEO, GDP, EPS, …) without duplicating
 * the list, and so future surfaces can reuse the same noise vocabulary.
 */
export const TICKER_NOISE_BLOCKLIST: ReadonlySet<string> = new Set(NOISE_TOKENS);

// ── Public types ──────────────────────────────────────────────────────────────

/**
 * Minimal message shape the extractor needs. Structurally compatible with
 * the frontend `Message` type (role + content) — callers pass Message[]
 * directly. Kept minimal so the unit tests don't have to fabricate full
 * Message objects (message_id, citations, …) for every table row.
 */
export interface TickerSourceMessage {
  role: "user" | "assistant";
  content: string;
}

/** Result of a capped extraction over a conversation. */
export interface TickerExtraction {
  /**
   * Deduped uppercase tickers, ordered most-recent-mention-first, capped
   * at the requested limit (default {@link DEFAULT_TICKER_CAP}).
   */
  tickers: string[];
  /**
   * How many ADDITIONAL distinct tickers were detected beyond the cap.
   * Drives the "+N more" overflow label in the rail. 0 when under the cap.
   */
  overflow: number;
}

/**
 * Default cap per the Round-2 spec: "~8 most recent with overflow count".
 * 8 mini-cards at ~52px each fit a 1080p rail without scrolling past the
 * citations section.
 */
export const DEFAULT_TICKER_CAP = 8;

// ── Implementation ────────────────────────────────────────────────────────────

/**
 * Extract candidate tickers from ONE text block, in order of appearance.
 * May contain duplicates — the conversation-level wrapper dedupes.
 *
 * Exported for direct table-driven testing of the per-text rules
 * ($-prefix bypass, blocklist, boundaries) without conversation plumbing.
 */
export function extractTickersFromText(text: string): string[] {
  const found: string[] = [];

  // Pass 1 — explicit $TICKER mentions (bypass blocklist + length-2 floor).
  // WHY a fresh RegExp per call: the module-level constants carry the /g
  // flag; sharing their lastIndex across calls is a classic stateful-regex
  // bug (every second call silently starts mid-string). Cloning per call
  // keeps the function pure.
  {
    const re = new RegExp(DOLLAR_TICKER_RE.source, "g");
    let m: RegExpExecArray | null;
    while ((m = re.exec(text)) !== null) {
      found.push(m[1]);
    }
  }

  // Pass 2 — bare uppercase tokens, blocklist-gated.
  {
    const re = new RegExp(BARE_TICKER_RE.source, "g");
    let m: RegExpExecArray | null;
    while ((m = re.exec(text)) !== null) {
      const token = m[1];
      // WHY skip $-prefixed occurrences here: pass 1 already captured them.
      // The bare regex would re-match the same letters (the `$` is a
      // non-word char so `\b` sits right after it); checking the preceding
      // char avoids double-processing — harmless for dedupe but it would
      // let a blocklisted $-token ("$GDP") be REJECTED by this pass after
      // being accepted by pass 1 if we naively unioned rejections. Accept
      // semantics are additive, so this guard is belt-and-braces clarity.
      const prev = m.index > 0 ? text[m.index - 1] : "";
      if (prev === "$") continue;
      if (!TICKER_NOISE_BLOCKLIST.has(token)) {
        found.push(token);
      }
    }
  }

  return found;
}

/**
 * extractTickers — conversation-level extraction.
 *
 * Scans messages NEWEST → OLDEST so the dedupe pass naturally ranks each
 * ticker by its most recent mention (first sighting in the scan = newest
 * mention in the thread). Within a single message, tokens keep their
 * left-to-right appearance order.
 *
 * @param messages Conversation log, oldest-first (the natural order the
 *                 chat page stores `localMessages` in).
 * @param cap      Max tickers to return (default {@link DEFAULT_TICKER_CAP}).
 */
export function extractTickers(
  messages: readonly TickerSourceMessage[],
  cap: number = DEFAULT_TICKER_CAP,
): TickerExtraction {
  const ordered: string[] = [];
  const seen = new Set<string>();

  // Newest message first → recency ranking falls out of insertion order.
  for (let i = messages.length - 1; i >= 0; i--) {
    for (const ticker of extractTickersFromText(messages[i].content)) {
      if (!seen.has(ticker)) {
        seen.add(ticker);
        ordered.push(ticker);
      }
    }
  }

  return {
    tickers: ordered.slice(0, cap),
    overflow: Math.max(0, ordered.length - cap),
  };
}
