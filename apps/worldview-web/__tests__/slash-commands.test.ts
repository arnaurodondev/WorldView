/**
 * __tests__/slash-commands.test.ts — unit tests for the slash command parser
 *
 * WHY THIS EXISTS (PLAN-0051 T-E-5-08):
 * The parser is the entry point for the inline-card UX. Buggy parsing means
 * either the LLM gets called for things it shouldn't (slow + costly) or the
 * card never renders for valid input (silent UX bug). Pinning every parser
 * with explicit tests catches regressions immediately.
 *
 * COVERAGE:
 *  - Each command kind parses correctly with valid input
 *  - Malformed args return null (and therefore fall through to the LLM)
 *  - Unknown verbs return null
 *  - Whitespace handling, case insensitivity, prefix filtering
 */

import { describe, it, expect } from "vitest";
import {
  parseInput,
  filterCommands,
  SLASH_COMMANDS,
} from "@/lib/chat/slash-commands";

describe("slash-commands.parseInput", () => {
  it("returns null when input does not start with /", () => {
    expect(parseInput("hello world")).toBeNull();
    expect(parseInput("")).toBeNull();
    expect(parseInput("  hi")).toBeNull();
    // Single character — too short to be a valid command.
    expect(parseInput("/")).toBeNull();
  });

  it("/quote AAPL -> kind=quote, params.ticker=AAPL (uppercased)", () => {
    const out = parseInput("/quote aapl");
    expect(out).not.toBeNull();
    expect(out?.kind).toBe("quote");
    expect(out?.params.ticker).toBe("AAPL");
  });

  it("/quote with no ticker returns null (parser fail open)", () => {
    expect(parseInput("/quote")).toBeNull();
    expect(parseInput("/quote   ")).toBeNull();
  });

  it("/quote with a non-alphabetic-leading ticker returns null (QA-iter1 NIT-2)", () => {
    // QA-iter1 NIT-2: a literal "0" or "12345" is not a real ticker — the
    // parser used to accept it and the gateway 404'd downstream. Now we
    // return null so the chat falls back to the LLM, which gives the user
    // a more helpful response than a broken card.
    expect(parseInput("/quote 0")).toBeNull();
    expect(parseInput("/quote 12345")).toBeNull();
    // But valid tickers (letter-leading) still parse.
    expect(parseInput("/quote BRK.B")?.kind).toBe("quote");
  });

  it("/portfolio with or without args returns the portfolio kind", () => {
    expect(parseInput("/portfolio")?.kind).toBe("portfolio");
    expect(parseInput("/portfolio main")?.kind).toBe("portfolio");
  });

  it("/news SECTOR=tech parses the SECTOR param into params.sector", () => {
    const out = parseInput("/news SECTOR=tech");
    expect(out?.kind).toBe("news");
    // Keys are lowercased; values keep case
    expect(out?.params.sector).toBe("tech");
  });

  it("/watchlist requires a name — bare '/watchlist' returns null", () => {
    expect(parseInput("/watchlist")).toBeNull();
    expect(parseInput("/watchlist Tech Movers")).toEqual({
      kind: "watchlist",
      params: { name: "Tech Movers" },
    });
  });

  it("/alerts and /screener accept no args and return their kind", () => {
    expect(parseInput("/alerts")?.kind).toBe("alerts");
    expect(parseInput("/screener")?.kind).toBe("screener");
  });

  it("unknown verbs return null (fall-through to LLM)", () => {
    expect(parseInput("/foobar AAPL")).toBeNull();
    expect(parseInput("/quotee AAPL")).toBeNull();
  });
});

describe("slash-commands.filterCommands", () => {
  it("returns full list when prefix is empty or just '/'", () => {
    expect(filterCommands("").length).toBe(SLASH_COMMANDS.length);
    expect(filterCommands("/").length).toBe(SLASH_COMMANDS.length);
  });

  it("filters by prefix on the verb name", () => {
    const matches = filterCommands("/qu");
    expect(matches.map((c) => c.name)).toEqual(["quote"]);
  });

  it("is case-insensitive", () => {
    const matches = filterCommands("/POR");
    expect(matches.map((c) => c.name)).toContain("portfolio");
  });
});
