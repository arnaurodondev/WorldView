/**
 * features/chat/lib/starters.ts — Empty-thread starter-question helpers.
 *
 * WHY EXTRACTED (PLAN-0059 E-3 partial): the constants + entityStarters
 * helper sat inline in `app/(app)/chat/page.tsx`. Pulling them out lets
 * any future "ask AI" entry point (e.g. the watchlist movers row's
 * right-click menu) reuse the same canonical starter phrasing.
 *
 * WHY pre-seeded cards: empty-thread state is a common UX dead zone —
 * users don't know what to ask first. Pre-seeded cards reduce blank-page
 * anxiety and guide traders toward high-value research questions.
 */

/**
 * PLACEHOLDER_THREAD_TITLE — shown until S9 processes the first message
 * via the LLM and emits a real title via the post-stream PATCH.
 */
export const PLACEHOLDER_THREAD_TITLE = "New conversation";

/**
 * STARTER_QUESTIONS — generic fallbacks shown when no entity context is set.
 *
 * The literal `[TICKER]` placeholder is intentional — when the user clicks
 * a card with an active entity context the placeholder is substituted in
 * the page handler. Without one (no entity set yet) the literal makes the
 * "fill in your ticker" prompt obvious.
 */
export const STARTER_QUESTIONS = [
  "What are the key risks for [TICKER] next quarter?",
  "Compare MSFT and GOOGL cloud revenue growth over 4 quarters",
  "Summarize [TICKER]'s latest earnings call",
  "Recent insider transactions and what they signal",
  "What analyst consensus shows for [TICKER] in 2026?",
  "Search SEC filings for 'supply chain' risk exposure",
] as const;

/**
 * entityStarters — context-aware starter questions when ?entity_id= is set.
 *
 * WHY a function (not a constant): we substitute the ticker into the strings
 * for a personalised feel ("What's the latest news on AAPL?" beats
 * "What's the latest news on [TICKER]?"). PLAN-0051 T-E-5-05.
 */
export function entityStarters(ticker: string): readonly string[] {
  return [
    `What's the latest news on ${ticker}?`,
    `Why did ${ticker} move today?`,
    `What are the bull and bear cases for ${ticker}?`,
    `How does ${ticker} compare to its peers?`,
  ];
}
