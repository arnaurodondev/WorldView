/**
 * lib/__tests__/command-palette.test.ts — Pure ranking/filtering contract for
 * the global ⌘K palette (Round-1 Command Palette).
 *
 * Pins the ranking contract:
 *   exact ticker match → ticker prefix match → server order,
 *   with recently-visited instruments floated within each tier,
 * plus nav substring matching and conversation recency sorting.
 */

import { describe, it, expect } from "vitest";
import {
  filterRecentThreads,
  matchesNavEntry,
  rankInstrumentResults,
  UNTITLED_THREAD_LABEL,
  type PaletteNavEntry,
  type RankableInstrument,
  type RankableThread,
} from "@/lib/command-palette";

// ── Fixtures ───────────────────────────────────────────────────────────────────

function inst(entityId: string, ticker: string, name = ticker): RankableInstrument {
  return { entity_id: entityId, ticker, name };
}

function thread(id: string, title: string | null, updatedAt: string): RankableThread {
  return { thread_id: id, title, updated_at: updatedAt };
}

// ── rankInstrumentResults ──────────────────────────────────────────────────────

describe("rankInstrumentResults", () => {
  it("puts the exact ticker match first even when the server returned it last", () => {
    // Server (ILIKE '%A%') order: AAPL, AA, A — exact match "A" arrives last.
    const results = [inst("e1", "AAPL"), inst("e2", "AA"), inst("e3", "A")];
    const ranked = rankInstrumentResults(results, "A");
    expect(ranked.map((r) => r.ticker)).toEqual(["A", "AAPL", "AA"]);
  });

  it("ranks ticker-prefix matches above name-only matches", () => {
    // "MS" matches Morgan Stanley's name via ILIKE but MSFT by ticker prefix.
    const results = [inst("e1", "MORG", "Morgan Stanley MS"), inst("e2", "MSFT", "Microsoft")];
    const ranked = rankInstrumentResults(results, "MS");
    expect(ranked.map((r) => r.ticker)).toEqual(["MSFT", "MORG"]);
  });

  it("is case-insensitive on the query", () => {
    const results = [inst("e1", "AAPL"), inst("e2", "AMZN")];
    const ranked = rankInstrumentResults(results, "aapl");
    expect(ranked[0]?.ticker).toBe("AAPL");
  });

  it("floats recently-visited instruments within the same tier", () => {
    // Both AAPL and AMZN are prefix matches for "A"; AMZN was visited recently.
    const results = [inst("e-aapl", "AAPL"), inst("e-amzn", "AMZN")];
    const ranked = rankInstrumentResults(results, "A", ["e-amzn"]);
    expect(ranked.map((r) => r.ticker)).toEqual(["AMZN", "AAPL"]);
  });

  it("recency does NOT outrank a better tier (exact beats recent prefix)", () => {
    // A (exact) must beat AAPL (prefix) even though AAPL is the recent one.
    const results = [inst("e-aapl", "AAPL"), inst("e-a", "A")];
    const ranked = rankInstrumentResults(results, "A", ["e-aapl"]);
    expect(ranked.map((r) => r.ticker)).toEqual(["A", "AAPL"]);
  });

  it("preserves server order for ties (stable sort)", () => {
    const results = [inst("e1", "ABC"), inst("e2", "ABD"), inst("e3", "ABE")];
    const ranked = rankInstrumentResults(results, "AB");
    expect(ranked.map((r) => r.ticker)).toEqual(["ABC", "ABD", "ABE"]);
  });

  it("does not mutate the input array", () => {
    const results = [inst("e1", "ZZ"), inst("e2", "AA")];
    const snapshot = [...results];
    rankInstrumentResults(results, "AA");
    expect(results).toEqual(snapshot);
  });

  it("returns everything in server order for an empty query", () => {
    const results = [inst("e1", "ZZ"), inst("e2", "AA")];
    expect(rankInstrumentResults(results, "").map((r) => r.ticker)).toEqual(["ZZ", "AA"]);
  });
});

// ── matchesNavEntry ────────────────────────────────────────────────────────────

describe("matchesNavEntry", () => {
  const entry: PaletteNavEntry = {
    label: "Portfolio › Transactions",
    path: "/portfolio/transactions",
    keywords: ["trades", "orders"],
  };

  it("matches case-insensitive label substrings", () => {
    expect(matchesNavEntry(entry, "transac")).toBe(true);
    expect(matchesNavEntry(entry, "PORT")).toBe(true);
  });

  it("matches via keywords", () => {
    expect(matchesNavEntry(entry, "trades")).toBe(true);
  });

  it("rejects non-matching queries", () => {
    expect(matchesNavEntry(entry, "screener")).toBe(false);
  });

  it("matches everything for an empty/whitespace query", () => {
    expect(matchesNavEntry(entry, "")).toBe(true);
    expect(matchesNavEntry(entry, "   ")).toBe(true);
  });
});

// ── filterRecentThreads ────────────────────────────────────────────────────────

describe("filterRecentThreads", () => {
  const threads = [
    thread("t-old", "Old chat about NVDA", "2026-06-01T10:00:00Z"),
    thread("t-new", "Fresh AAPL discussion", "2026-06-09T10:00:00Z"),
    thread("t-mid", null, "2026-06-05T10:00:00Z"),
  ];

  it("sorts newest-first by updated_at", () => {
    const result = filterRecentThreads(threads, "");
    expect(result.map((t) => t.thread_id)).toEqual(["t-new", "t-mid", "t-old"]);
  });

  it("truncates to the limit AFTER sorting", () => {
    const result = filterRecentThreads(threads, "", 2);
    expect(result.map((t) => t.thread_id)).toEqual(["t-new", "t-mid"]);
  });

  it("filters by title substring (case-insensitive)", () => {
    const result = filterRecentThreads(threads, "nvda");
    expect(result.map((t) => t.thread_id)).toEqual(["t-old"]);
  });

  it("matches untitled threads via the fallback label", () => {
    const result = filterRecentThreads(threads, UNTITLED_THREAD_LABEL.slice(0, 5).toLowerCase());
    expect(result.map((t) => t.thread_id)).toEqual(["t-mid"]);
  });

  it("does not mutate the input array (TanStack cache safety)", () => {
    const snapshot = [...threads];
    filterRecentThreads(threads, "");
    expect(threads).toEqual(snapshot);
  });

  it("sinks unparseable timestamps to the bottom instead of corrupting the sort", () => {
    const withBad = [...threads, thread("t-bad", "Corrupt", "not-a-date")];
    const result = filterRecentThreads(withBad, "", 10);
    expect(result[result.length - 1]?.thread_id).toBe("t-bad");
  });
});
