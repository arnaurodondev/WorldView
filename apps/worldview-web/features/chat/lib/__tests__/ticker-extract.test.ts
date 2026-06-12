/**
 * features/chat/lib/__tests__/ticker-extract.test.ts — Round 2 Enhancement.
 *
 * Table-driven tests for the conversation ticker extractor. WHAT THESE GUARD:
 *   1. $TICKER detection — always counts, even for blocklisted tokens and
 *      single letters ($F = Ford).
 *   2. Bare TICKER detection — 2–5 uppercase letters, word-bounded.
 *   3. Noise blocklist — CEO/GDP/EPS/VERY/etc. never count as bare tokens.
 *   4. Word boundaries — no matches inside mixed-case or digit-glued tokens.
 *   5. Dedupe — a ticker mentioned N times yields exactly one entry.
 *   6. Recency ordering — most recent mention ranks first.
 *   7. Cap + overflow — default 8, overflow counts the remainder.
 */

import { describe, it, expect } from "vitest";

import {
  DEFAULT_TICKER_CAP,
  TICKER_NOISE_BLOCKLIST,
  extractTickers,
  extractTickersFromText,
  type TickerSourceMessage,
} from "../ticker-extract";

/** Shorthand: build a message list from plain strings (alternating roles
 *  don't matter to the extractor — both roles are scanned). */
function msgs(...contents: string[]): TickerSourceMessage[] {
  return contents.map((content, i) => ({
    role: i % 2 === 0 ? "user" : "assistant",
    content,
  }));
}

// ── extractTickersFromText — per-text rule table ─────────────────────────────

describe("extractTickersFromText", () => {
  // Each row: [description, input text, expected tickers (in order)].
  const TABLE: Array<[string, string, string[]]> = [
    // ── $-prefixed: always counts ──
    ["$ + 4 letters", "buy $AAPL today", ["AAPL"]],
    ["$ + 1 letter (Ford)", "is $F cheap?", ["F"]],
    ["$ bypasses blocklist", "what about $GDP and $AI?", ["GDP", "AI"]],
    ["$ at start of string", "$NVDA earnings", ["NVDA"]],
    ["$ at end of string", "thoughts on $TSM", ["TSM"]],
    ["$ followed by punctuation", "compare $AMD, $INTC.", ["AMD", "INTC"]],
    ["$ lowercase NOT matched", "i have $cash and $aapl", []],
    ["$ + 6 letters NOT matched (max 5)", "$ABCDEF is not a ticker", []],
    // ── bare tokens: blocklist-gated ──
    ["bare 4-letter ticker", "compare NVDA with peers", ["NVDA"]],
    ["bare 2-letter ticker", "GM reported strong trucks", ["GM"]],
    ["multiple bare tickers keep order", "NVDA beat, AMD missed", ["NVDA", "AMD"]],
    ["bare single letter NEVER counts", "I bought A share", []],
    ["bare blocklisted: CEO", "the CEO resigned", []],
    ["bare blocklisted: GDP/EPS/CPI", "GDP rose; EPS beat; CPI cooled", []],
    ["bare blocklisted: currencies", "USD vs EUR vs JPY", []],
    ["bare blocklisted: AI/API/ETF/SEC/FED", "AI ETF filings at the SEC, FED watch, API docs", []],
    ["bare blocklisted: VERY (caps emphasis)", "I am VERY bullish", []],
    ["bare blocklisted: US/UK/NYSE", "US and UK markets on the NYSE", []],
    // ── word boundaries ──
    ["mixed case not matched", "Apple and Nvidia rallied", []],
    ["digit-glued not matched", "the 10K and 8K filings", []],
    ["ticker followed by digits not matched", "code AAPL5 is internal", []],
    ["inside-markdown-bold matched (asterisks are non-word)", "**NVDA** rallied", ["NVDA"]],
    ["parenthesised matched", "NVIDIA (NVDA) is up", ["NVDA"]],
    ["possessive matched", "TSM's capex grew", ["TSM"]],
    // ── mixed $ and bare ──
    [
      "$ pass runs before bare pass",
      "compare $AMD with NVDA",
      ["AMD", "NVDA"],
    ],
    ["empty string", "", []],
  ];

  it.each(TABLE)("%s: %j → %j", (_desc, text, expected) => {
    expect(extractTickersFromText(text)).toEqual(expected);
  });
});

// ── Blocklist sanity ─────────────────────────────────────────────────────────

describe("TICKER_NOISE_BLOCKLIST", () => {
  it("contains the spec-mandated noise tokens", () => {
    // The task spec calls these out explicitly — pin them so a future
    // blocklist refactor can't silently drop one.
    const required = [
      "CEO", "CFO", "GDP", "EPS", "PE", "YOY", "TTM", "USD", "EUR",
      "AI", "API", "IPO", "ETF", "SEC", "FED", "US", "UK", "NYSE",
    ];
    for (const token of required) {
      expect(TICKER_NOISE_BLOCKLIST.has(token), `${token} must be blocklisted`).toBe(true);
    }
  });
});

// ── extractTickers — conversation-level behaviour ────────────────────────────

describe("extractTickers", () => {
  it("dedupes a ticker mentioned in multiple messages", () => {
    const result = extractTickers(
      msgs("$AAPL is up", "Yes, $AAPL gained 3% — AAPL leads megacaps"),
    );
    expect(result.tickers).toEqual(["AAPL"]);
    expect(result.overflow).toBe(0);
  });

  it("orders tickers most-recent-mention-first", () => {
    // AAPL appears first chronologically, TSM last — TSM must rank first.
    const result = extractTickers(
      msgs("tell me about $AAPL", "AAPL is strong", "now compare with $TSM"),
    );
    expect(result.tickers).toEqual(["TSM", "AAPL"]);
  });

  it("a re-mention promotes an old ticker back to the front", () => {
    const result = extractTickers(
      msgs("$AAPL first", "$NVDA next", "back to $AAPL again"),
    );
    // AAPL's most recent mention (message 3) is newer than NVDA's (message 2).
    expect(result.tickers).toEqual(["AAPL", "NVDA"]);
  });

  it(`caps at DEFAULT_TICKER_CAP (${DEFAULT_TICKER_CAP}) and reports overflow`, () => {
    // 10 distinct tickers in one message → 8 returned + overflow 2.
    const ten = ["AAPL", "NVDA", "AMD", "TSM", "MSFT", "GOOG", "AMZN", "META", "TSLA", "INTC"];
    const result = extractTickers(msgs(ten.map((t) => `$${t}`).join(" ")));
    expect(result.tickers).toHaveLength(DEFAULT_TICKER_CAP);
    expect(result.overflow).toBe(ten.length - DEFAULT_TICKER_CAP);
    // Within a single message, appearance order is preserved.
    expect(result.tickers).toEqual(ten.slice(0, DEFAULT_TICKER_CAP));
  });

  it("respects a custom cap", () => {
    const result = extractTickers(msgs("$AAPL $NVDA $AMD"), 2);
    expect(result.tickers).toEqual(["AAPL", "NVDA"]);
    expect(result.overflow).toBe(1);
  });

  it("returns empty extraction for an empty conversation", () => {
    expect(extractTickers([])).toEqual({ tickers: [], overflow: 0 });
  });

  it("returns empty extraction when only noise tokens appear", () => {
    const result = extractTickers(
      msgs("The CEO discussed GDP and CPI with the FED — VERY bullish IMO"),
    );
    expect(result.tickers).toEqual([]);
    expect(result.overflow).toBe(0);
  });

  it("scans both user and assistant messages", () => {
    const result = extractTickers([
      { role: "user", content: "what moved $AAPL?" },
      { role: "assistant", content: "Mostly the TSM supply news." },
    ]);
    // TSM (assistant, newer) ranks before AAPL (user, older).
    expect(result.tickers).toEqual(["TSM", "AAPL"]);
  });
});

// ── Wave 3 — conference/event token blocklist ─────────────────────────────────
//
// LIVE FALSE POSITIVE (2026-06-11): "WWDC" (Apple's developer conference) was
// detected as a bare ticker in a real conversation, contributing to the
// ENTITY OVERVIEW count-without-cards bug. Conference acronyms are pervasive
// in finance/tech prose and never primary-listing tickers.

describe("extractTickersFromText — conference tokens (Wave 3)", () => {
  it.each(["WWDC", "CES", "MWC", "GTC", "SXSW", "IFA", "EXPO", "DAVOS"])(
    "blocklists bare %s",
    (token) => {
      expect(extractTickersFromText(`Big news out of ${token} this week`)).toEqual(
        [],
      );
    },
  );

  it("the $ prefix still force-detects a blocklisted conference token", () => {
    // The explicit-intent escape hatch must keep working — if a ticker ever
    // shares a conference acronym, "$WWDC" is the analyst's override. The
    // resolve-before-render safety net drops it later when it doesn't exist.
    expect(extractTickersFromText("track $WWDC")).toEqual(["WWDC"]);
  });

  it("conference token in real prose: detects the ticker but not the event", () => {
    expect(
      extractTickersFromText("AAPL previewed new AI features at WWDC"),
    ).toEqual(["AAPL"]);
  });
});
