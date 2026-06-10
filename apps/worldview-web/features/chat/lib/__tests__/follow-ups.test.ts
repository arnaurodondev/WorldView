/**
 * features/chat/lib/__tests__/follow-ups.test.ts — Round 2 Enhancement.
 *
 * Tests for the deterministic follow-up chip generator. WHAT THESE GUARD:
 *   1. Determinism — identical context always yields identical chips
 *      (no Math.random; chips must not reshuffle across re-renders).
 *   2. Exactly FOLLOW_UP_COUNT distinct chips in every case.
 *   3. Entity substitution — detected tickers appear in the chip text.
 *   4. Pair comparison chip when ≥2 tickers are in context.
 *   5. Tool-aware chips (price history / contradictions / fundamentals).
 *   6. Citation deep-dive chip + title truncation.
 *   7. No-entity fallback — generic pool only, never a placeholder leak.
 *   8. Variety — different answers select different template variants.
 */

import { describe, it, expect } from "vitest";

import {
  FOLLOW_UP_COUNT,
  generateFollowUps,
  type FollowUpContext,
} from "../follow-ups";

/** Context factory with empty defaults so each test states only its signal. */
function ctx(overrides: Partial<FollowUpContext> = {}): FollowUpContext {
  return {
    answerText: "NVDA posted strong datacenter revenue growth this quarter.",
    tickers: [],
    citationTitles: [],
    toolsUsed: [],
    ...overrides,
  };
}

describe("generateFollowUps", () => {
  // ── Core contract ──────────────────────────────────────────────────────────

  it(`always returns exactly ${FOLLOW_UP_COUNT} distinct suggestions`, () => {
    // Exercise every signal combination — the count contract must hold for all.
    const cases: FollowUpContext[] = [
      ctx(), // nothing
      ctx({ tickers: ["NVDA"] }),
      ctx({ tickers: ["NVDA", "AMD", "TSM"] }),
      ctx({ toolsUsed: ["get_price_history"] }),
      ctx({ citationTitles: ["Some article"] }),
      ctx({
        tickers: ["AAPL"],
        toolsUsed: ["search_documents", "get_fundamentals"],
        citationTitles: ["Apple 10-Q", "Supply chain note"],
      }),
    ];
    for (const c of cases) {
      const out = generateFollowUps(c);
      expect(out).toHaveLength(FOLLOW_UP_COUNT);
      expect(new Set(out).size).toBe(FOLLOW_UP_COUNT);
      // Every chip is non-empty prose.
      for (const s of out) expect(s.trim().length).toBeGreaterThan(0);
    }
  });

  it("is deterministic — identical context yields identical chips", () => {
    const c = ctx({
      tickers: ["NVDA", "AMD"],
      toolsUsed: ["get_price_history"],
      citationTitles: ["NVIDIA Q2 results"],
    });
    const a = generateFollowUps(c);
    const b = generateFollowUps({ ...c });
    expect(a).toEqual(b);
  });

  // ── Entity substitution ────────────────────────────────────────────────────

  it("substitutes the primary (most recent) ticker into chip text", () => {
    const out = generateFollowUps(ctx({ tickers: ["NVDA"] }));
    // At least one chip must name the entity — that's the whole point of
    // context-aware suggestions vs canned generics.
    expect(out.some((s) => s.includes("NVDA"))).toBe(true);
    // And no chip may reference an entity that was NOT in context.
    expect(out.some((s) => s.includes("AAPL"))).toBe(false);
  });

  it("adds a head-to-head comparison chip when 2+ tickers are detected", () => {
    const out = generateFollowUps(ctx({ tickers: ["NVDA", "AMD", "TSM"] }));
    // Pair template uses the two MOST RECENT tickers (positions 0 and 1).
    expect(out).toContain("Compare NVDA and AMD head-to-head");
  });

  it("does NOT add a comparison chip for a single ticker", () => {
    const out = generateFollowUps(ctx({ tickers: ["NVDA"] }));
    expect(out.some((s) => s.startsWith("Compare "))).toBe(false);
  });

  // ── Tool-aware chips ───────────────────────────────────────────────────────

  it("suggests a price-trend follow-up when the agent used a price tool", () => {
    const out = generateFollowUps(
      ctx({ tickers: ["NVDA"], toolsUsed: ["get_price_history"] }),
    );
    expect(out).toContain("Show NVDA's longer-term price trend");
  });

  it("degrades tool chips to entity-free phrasing without a ticker", () => {
    const out = generateFollowUps(ctx({ toolsUsed: ["get_contradictions"] }));
    expect(out).toContain("Are there contradicting claims on this topic?");
  });

  it("uses the FIRST recognised tool when several ran", () => {
    const out = generateFollowUps(
      ctx({
        tickers: ["AAPL"],
        // Invocation order: fundamentals first → its template must win.
        toolsUsed: ["get_fundamentals", "get_price_history"],
      }),
    );
    expect(out).toContain("Break down AAPL's latest fundamentals");
    expect(out).not.toContain("Show AAPL's longer-term price trend");
  });

  // ── Citation chips ─────────────────────────────────────────────────────────

  it("offers a deep-dive on a cited source", () => {
    const out = generateFollowUps(
      ctx({ citationTitles: ["Apple Reports Record Q2"] }),
    );
    expect(out).toContain('Tell me more about "Apple Reports Record Q2"');
  });

  it("truncates long citation titles with an ellipsis", () => {
    const longTitle =
      "Apple Reports Record Second Quarter Results Amid Persistent Supply Chain Headwinds In Asia";
    const out = generateFollowUps(ctx({ citationTitles: [longTitle] }));
    const chip = out.find((s) => s.startsWith("Tell me more about"));
    expect(chip).toBeDefined();
    expect(chip).toContain("…");
    // Quoted fragment must be bounded (50-char cap + quotes + prefix).
    expect(chip!.length).toBeLessThan(80);
    // The raw 90-char title must NOT appear verbatim.
    expect(chip).not.toContain(longTitle);
  });

  it("skips blank citation titles instead of rendering empty quotes", () => {
    const out = generateFollowUps(ctx({ citationTitles: ["", "   "] }));
    expect(out.some((s) => s.startsWith("Tell me more about"))).toBe(false);
  });

  // ── No-entity fallback ─────────────────────────────────────────────────────

  it("falls back to generic suggestions when no signals exist", () => {
    const out = generateFollowUps(
      ctx({ answerText: "Duration risk rises when rates fall." }),
    );
    expect(out).toHaveLength(FOLLOW_UP_COUNT);
    // No template placeholder may ever leak into the UI.
    for (const s of out) {
      expect(s).not.toMatch(/<TICKER>|undefined|null/);
    }
  });

  // ── Variety ────────────────────────────────────────────────────────────────

  it("varies template selection across different answers (not canned)", () => {
    // 12 different answer texts about the same entity — the hash rotation
    // must produce more than one distinct leading ticker-chip overall,
    // otherwise every NVDA answer would suggest the exact same question.
    const firstChips = new Set(
      Array.from({ length: 12 }, (_, i) =>
        generateFollowUps(
          ctx({ answerText: `Answer variant number ${i} about the GPU cycle.`, tickers: ["NVDA"] }),
        )[0],
      ),
    );
    expect(firstChips.size).toBeGreaterThan(1);
  });
});
