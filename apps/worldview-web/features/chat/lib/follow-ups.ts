/**
 * features/chat/lib/follow-ups.ts — Deterministic client-side generator for
 * the "suggested follow-up" chips shown under a completed assistant answer.
 *
 * WHY CLIENT-SIDE (Round 2 Enhancement — Chat surface):
 * The S8 SSE stream emits no `suggestions`/`follow_ups` event today (verified
 * in useChatStream's demux: token / citations / tool_call / tool_result /
 * agent_iteration / pending_action / error / done — nothing else). Until the
 * backend grows one, we synthesise follow-ups from the signals the turn
 * already produced: detected tickers, citation titles, and the tools the
 * agent invoked. If S8 ever emits server-side suggestions, the page should
 * prefer those and this module becomes the fallback (documented backend gap).
 *
 * WHY DETERMINISTIC (no Math.random):
 *   1. Testability — same context must always yield the same chips so the
 *      Vitest suite can pin exact outputs.
 *   2. Render stability — the chips memo recomputes whenever the message
 *      list identity changes; randomness would make chips visibly reshuffle
 *      on unrelated re-renders, which reads as a glitch.
 * Variety comes from a content hash instead: different answers select
 * different template variants, so consecutive turns don't feel canned even
 * though each individual turn is fully reproducible.
 *
 * PURITY: no React, no fetch, no Date — pure function of its input.
 */

// ── Public types ──────────────────────────────────────────────────────────────

/** Everything the generator knows about the completed assistant turn. */
export interface FollowUpContext {
  /** Full markdown text of the assistant answer (drives the variety hash). */
  answerText: string;
  /**
   * Detected ticker symbols, most-recent-first (output of
   * `extractTickers().tickers`). May be empty — generic templates kick in.
   */
  tickers: readonly string[];
  /** Titles of the citations attached to the answer (may be empty). */
  citationTitles: readonly string[];
  /**
   * Internal tool names the agent invoked during the turn (from the
   * `toolTrace` the stream hook records), e.g. "get_price_history".
   */
  toolsUsed: readonly string[];
}

/** Exactly how many chips the generator returns (FollowUpChips caps at 4). */
export const FOLLOW_UP_COUNT = 3;

// ── Deterministic hash ────────────────────────────────────────────────────────

/**
 * Tiny FNV-1a–style string hash. NOT cryptographic — it only needs to spread
 * template selection across answers. 32-bit unsigned output.
 *
 * WHY not djb2/charCodeAt-sum: a plain char-sum collides for anagrams and
 * short strings, which would make "AAPL up" and "AAPL pu" pick identical
 * variants suspiciously often. FNV-1a mixes positions properly for ~3 LOC.
 */
function hashString(s: string): number {
  let h = 0x811c9dc5;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    // 32-bit FNV prime multiply via shifts (keeps everything in int range).
    h = (h + ((h << 1) + (h << 4) + (h << 7) + (h << 8) + (h << 24))) >>> 0;
  }
  return h >>> 0;
}

// ── Template library ──────────────────────────────────────────────────────────
//
// WHY template FUNCTIONS (not string.replace on "<TICKER>" markers): template
// literals are type-checked — a typo'd placeholder fails at compile time
// instead of leaking "<TICKER>" into the UI.

/** Single-ticker questions. The hash picks a starting offset for variety. */
const TICKER_TEMPLATES: ReadonlyArray<(t: string) => string> = [
  (t) => `How does ${t}'s valuation compare to peers?`,
  (t) => `What are the key risks for ${t}?`,
  (t) => `Summarize recent news on ${t}`,
  (t) => `What's the analyst sentiment on ${t}?`,
  (t) => `What catalysts could move ${t} next?`,
  (t) => `How has ${t} performed over the past quarter?`,
];

/** Two-ticker comparison — used when the turn mentioned ≥2 entities. */
const PAIR_TEMPLATE = (a: string, b: string): string =>
  `Compare ${a} and ${b} head-to-head`;

/**
 * Tool-aware follow-ups: when the agent already used a tool, the natural
 * next question often deepens that same lane. Keyed by SUBSTRING match on
 * the internal tool name so minor backend renames ("get_price_history" →
 * "get_price_history_v2") keep matching.
 *
 * The ticker argument is the primary detected ticker or null; templates
 * degrade to entity-free phrasing when no ticker was detected.
 */
const TOOL_TEMPLATES: ReadonlyArray<{
  match: string;
  template: (t: string | null) => string;
}> = [
  {
    match: "price_history",
    template: (t) =>
      t ? `Show ${t}'s longer-term price trend` : "Show the longer-term price trend",
  },
  {
    match: "contradiction",
    template: () => "Are there contradicting claims on this topic?",
  },
  {
    match: "fundamental",
    template: (t) =>
      t ? `Break down ${t}'s latest fundamentals` : "Break down the latest fundamentals",
  },
  {
    match: "entity_graph",
    template: (t) =>
      t
        ? `Who are ${t}'s key partners and competitors?`
        : "Which related entities should I look at?",
  },
  {
    match: "search",
    template: () => "What do the primary sources say about this?",
  },
];

/**
 * Generic fallback pool — used when the turn produced no tickers, no usable
 * citations, and no recognised tools, and to pad up to FOLLOW_UP_COUNT.
 * Phrased to be sensible after ANY market-intelligence answer.
 */
const GENERIC_TEMPLATES: readonly string[] = [
  "What are the biggest risks to this view?",
  "Summarize the key takeaways in three bullets",
  "What would the bear case be?",
  "What macro events this week could change this?",
  "Which sectors are most exposed to this theme?",
  "What should I watch next on this topic?",
];

/**
 * Citation titles can be long ("Apple Reports Record Q2 2026 Results Amid…").
 * Chips must stay scannable, so we hard-truncate with an ellipsis.
 */
const CITATION_TITLE_MAX = 50;

function truncate(s: string, max: number): string {
  return s.length <= max ? s : `${s.slice(0, max - 1).trimEnd()}…`;
}

// ── Generator ─────────────────────────────────────────────────────────────────

/**
 * generateFollowUps — produce exactly {@link FOLLOW_UP_COUNT} distinct
 * follow-up questions for a completed assistant turn.
 *
 * SELECTION ORDER (highest-signal first):
 *   1. Two-ticker comparison when ≥2 entities were detected — the analyst
 *      explicitly has multiple names in play; comparison is the most likely
 *      next move on a terminal.
 *   2. Single-ticker template(s) for the primary (most recent) ticker —
 *      hash-rotated through the 6-variant pool so different answers about
 *      the same stock still suggest different angles.
 *   3. One tool-aware chip when the agent used a recognised tool.
 *   4. One citation deep-dive chip when the answer cited sources.
 *   5. Generic pool (hash-rotated) pads the remainder — guarantees we ALWAYS
 *      return 3 chips even for an entity-free answer ("explain duration risk").
 *
 * All candidates flow through a Set-based dedupe so a tool chip and a ticker
 * chip that happen to collide can't render twice.
 */
export function generateFollowUps(ctx: FollowUpContext): string[] {
  // Seed mixes the answer text AND the detected tickers: two answers with
  // identical prose but different entity context should still vary.
  const seed = hashString(ctx.answerText + "|" + ctx.tickers.join(","));

  const primary = ctx.tickers.length > 0 ? ctx.tickers[0] : null;
  const out: string[] = [];
  const seen = new Set<string>();
  const push = (s: string) => {
    if (out.length < FOLLOW_UP_COUNT && !seen.has(s)) {
      seen.add(s);
      out.push(s);
    }
  };

  // 1 — pair comparison.
  if (ctx.tickers.length >= 2) {
    push(PAIR_TEMPLATE(ctx.tickers[0], ctx.tickers[1]));
  }

  // 2 — single-ticker variants, rotated by the seed. We walk the pool from
  // a hash-picked offset and take as many as needed; the modulo walk visits
  // every variant exactly once, so dedupe never starves the loop.
  if (primary) {
    for (
      let i = 0;
      i < TICKER_TEMPLATES.length && out.length < FOLLOW_UP_COUNT - 1;
      i++
    ) {
      const idx = (seed + i) % TICKER_TEMPLATES.length;
      push(TICKER_TEMPLATES[idx](primary));
      // WHY stop after one when other signal classes remain: a wall of three
      // near-identical "${T} …?" chips feels canned (the spec's explicit
      // anti-goal). One ticker chip + one tool/citation/generic chip mixes
      // the angles. We allow a second ticker chip only when the turn has no
      // tool and no citation signals to draw from (checked below by the
      // remaining-capacity padding loop).
      if (ctx.toolsUsed.length > 0 || ctx.citationTitles.length > 0) break;
    }
  }

  // 3 — tool-aware chip (first recognised tool wins; toolsUsed preserves
  // the agent's invocation order, so "first" = earliest tool in the turn).
  for (const tool of ctx.toolsUsed) {
    const hit = TOOL_TEMPLATES.find((t) => tool.includes(t.match));
    if (hit) {
      push(hit.template(primary));
      break;
    }
  }

  // 4 — citation deep-dive. Hash-pick ONE title so multi-source answers
  // don't always surface the same first citation.
  if (ctx.citationTitles.length > 0) {
    const usable = ctx.citationTitles.filter((t) => t.trim().length > 0);
    if (usable.length > 0) {
      const title = usable[seed % usable.length];
      push(`Tell me more about "${truncate(title.trim(), CITATION_TITLE_MAX)}"`);
    }
  }

  // 5 — pad from the generic pool, rotated by the seed. The pool (6) is
  // larger than FOLLOW_UP_COUNT (3), so even with collisions against the
  // chips above we always reach 3.
  for (let i = 0; i < GENERIC_TEMPLATES.length && out.length < FOLLOW_UP_COUNT; i++) {
    push(GENERIC_TEMPLATES[(seed + i) % GENERIC_TEMPLATES.length]);
  }

  return out;
}
