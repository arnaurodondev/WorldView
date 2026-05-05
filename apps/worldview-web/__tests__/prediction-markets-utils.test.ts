/**
 * __tests__/prediction-markets-utils.test.ts — Unit tests for lib/prediction-markets.ts
 *
 * WHY THIS EXISTS: categorize() and formatCountdown() are the shared logic
 * consumed by both PredictionMarketsWidget and the /prediction-markets page.
 * Extracting them to a shared lib (PLAN-0068 C-2-02) without tests would create
 * a blind spot — any drift in the keyword lists or date math would silently
 * mis-categorise markets for all consumers.
 *
 * COVERAGE:
 *   categorize() — all 5 output categories + edge cases (empty, mixed-case,
 *                  first-match-wins collision, unknown title)
 *   formatCountdown() — all 4 output states (—, closed, closes today, closes in Nd)
 *
 * DATA SOURCE: No I/O — pure unit tests.
 */

import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import {
  categorize,
  formatCountdown,
  MACRO_KEYWORDS,
  POLITICS_KEYWORDS,
  SPORTS_KEYWORDS,
  CRYPTO_KEYWORDS,
} from "@/lib/prediction-markets";

// ── categorize() ──────────────────────────────────────────────────────────────

describe("categorize", () => {
  it.each([
    // macro — each keyword in the list triggers the bucket
    ["Fed raises interest rates by 25bp", "macro"],
    ["Will US inflation exceed 3% in 2025?", "macro"],
    ["GDP growth above 2% in Q4?", "macro"],
    ["Will the FOMC cut in March?", "macro"],
    ["Will tariff exemptions be extended?", "macro"],
    // politics
    ["Will Trump win the 2024 election?", "politics"],
    ["Presidential approval above 50%?", "politics"],
    ["Will the Senate pass the bill?", "politics"],
    ["Will the governor sign the budget?", "politics"],
    // sports
    ["NBA championship winner 2025?", "sports"],
    ["Super Bowl winner?", "sports"],
    ["Will Messi win the World Cup?", "sports"],
    ["F1 constructor champion 2025?", "sports"],
    // crypto
    ["Will Bitcoin exceed $100k?", "crypto"],
    ["Ethereum above $5k by end of year?", "crypto"],
    ["Will Solana flip ETH by market cap?", "crypto"],
    // general (no keyword match)
    ["Will Elon Musk tweet more than 10 times today?", "general"],
    ["Will SpaceX launch before June?", "general"],
    ["Celebrity A and B divorce?", "general"],
  ] as const)(
    "categorizes %s → %s",
    (title, expected) => {
      expect(categorize(title)).toBe(expected);
    },
  );

  it("is case-insensitive", () => {
    expect(categorize("WILL THE FED RAISE RATES?")).toBe("macro");
    expect(categorize("NBA FINALS 2025")).toBe("sports");
    expect(categorize("BITCOIN TO $200K")).toBe("crypto");
  });

  it("returns 'general' for an empty string", () => {
    expect(categorize("")).toBe("general");
  });

  it("first-match wins — macro beats crypto when both keywords present", () => {
    // "rate" (macro) appears before "bitcoin" (crypto) in the keyword order,
    // so the macro bucket wins for a title that contains both.
    expect(categorize("Fed rate decision and Bitcoin surge")).toBe("macro");
  });

  it("first-match wins — politics beats sports for 'olympic vote'", () => {
    // "vote" is in POLITICS_KEYWORDS which is checked before SPORTS_KEYWORDS.
    expect(categorize("IOC vote on 2036 Olympic host city")).toBe("politics");
  });

  it("exports keyword arrays that are non-empty", () => {
    expect(MACRO_KEYWORDS.length).toBeGreaterThan(0);
    expect(POLITICS_KEYWORDS.length).toBeGreaterThan(0);
    expect(SPORTS_KEYWORDS.length).toBeGreaterThan(0);
    expect(CRYPTO_KEYWORDS.length).toBeGreaterThan(0);
  });
});

// ── formatCountdown() ─────────────────────────────────────────────────────────

describe("formatCountdown", () => {
  // Fix the clock so date comparisons are deterministic.
  // "now" = 2026-05-05T12:00:00Z
  const NOW_ISO = "2026-05-05T12:00:00.000Z";

  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date(NOW_ISO));
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("returns '—' for null input", () => {
    expect(formatCountdown(null)).toBe("—");
  });

  it("returns '—' for undefined input", () => {
    expect(formatCountdown(undefined)).toBe("—");
  });

  it("returns '—' for an empty string", () => {
    expect(formatCountdown("")).toBe("—");
  });

  it("returns '—' for an invalid date string", () => {
    expect(formatCountdown("not-a-date")).toBe("—");
  });

  it("returns 'closed' for a past timestamp", () => {
    // 1 hour in the past
    expect(formatCountdown("2026-05-05T11:00:00.000Z")).toBe("closed");
  });

  it("returns 'closed' for a timestamp equal to now", () => {
    expect(formatCountdown(NOW_ISO)).toBe("closed");
  });

  it("returns 'closes today' for a timestamp later the same UTC day", () => {
    // 3 hours in the future, still the same UTC day
    expect(formatCountdown("2026-05-05T15:00:00.000Z")).toBe("closes today");
  });

  it("returns 'closes in 1d' for a timestamp just after midnight tomorrow UTC", () => {
    // One calendar day later — 12h + a bit past midnight next UTC day
    expect(formatCountdown("2026-05-06T00:30:00.000Z")).toBe("closes in 1d");
  });

  it("returns 'closes in 2d' for a timestamp 1.5 days away (rounds up)", () => {
    // 1.5 days = 36 hours — should ceil to 2
    expect(formatCountdown("2026-05-07T00:00:00.000Z")).toBe("closes in 2d");
  });

  it("returns 'closes in 7d' for a timestamp exactly 7 days away", () => {
    expect(formatCountdown("2026-05-12T12:00:00.000Z")).toBe("closes in 7d");
  });
});
