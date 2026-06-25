/**
 * features/dashboard/lib/__tests__/market-clock.test.ts — session engine tests
 *
 * WHY THESE TESTS: the session math is the riskiest part of the MarketClock
 * widget (time zones, DST, weekends, holidays, boundary minutes). Every
 * branch of getMarketSession is pinned here with FIXED UTC instants — no
 * Date.now(), no fake timers — so failures are deterministic and the suite
 * is immune to the wall clock of the CI machine.
 *
 * TIME ZONE CHEAT SHEET used throughout (America/New_York):
 *   June 2026   → EDT = UTC-4  (e.g. 09:30 ET = 13:30 UTC)
 *   January/November 2026 → EST = UTC-5  (e.g. 09:30 ET = 14:30 UTC)
 */

import { describe, it, expect } from "vitest";
import {
  formatCountdown,
  formatNyClock,
  getMarketSession,
  isTradingDay,
  nyWallTimeToUtc,
  NYSE_FULL_HOLIDAYS_2026,
  SESSION_LABEL,
} from "@/features/dashboard/lib/market-clock";

// Wed 2026-06-10 is a regular trading day (the Round 2 implementation date).
const utc = (iso: string) => new Date(iso);

describe("nyWallTimeToUtc", () => {
  it("converts a summer (EDT, UTC-4) wall time", () => {
    expect(nyWallTimeToUtc(2026, 6, 10, 9, 30).toISOString()).toBe(
      "2026-06-10T13:30:00.000Z",
    );
  });

  it("converts a winter (EST, UTC-5) wall time", () => {
    expect(nyWallTimeToUtc(2026, 1, 5, 9, 30).toISOString()).toBe(
      "2026-01-05T14:30:00.000Z",
    );
  });
});

describe("isTradingDay", () => {
  it("true on a regular weekday", () => {
    expect(isTradingDay(2026, 6, 10)).toBe(true); // Wednesday
  });
  it("false on Saturday and Sunday", () => {
    expect(isTradingDay(2026, 6, 13)).toBe(false); // Saturday
    expect(isTradingDay(2026, 6, 14)).toBe(false); // Sunday
  });
  it("false on every listed 2026 full holiday", () => {
    for (const key of NYSE_FULL_HOLIDAYS_2026) {
      const [y, m, d] = key.split("-").map(Number);
      expect(isTradingDay(y, m, d)).toBe(false);
    }
  });
});

describe("getMarketSession — weekday session cycle (EDT)", () => {
  it("pre-market at 08:00 ET, next transition = today 09:30 ET", () => {
    const s = getMarketSession(utc("2026-06-10T12:00:00Z")); // 08:00 ET
    expect(s.state).toBe("pre");
    expect(s.nextLabel).toBe("opens");
    expect(s.nextTransition.toISOString()).toBe("2026-06-10T13:30:00.000Z");
    expect(s.closedReason).toBeUndefined();
  });

  it("regular at exactly 09:30 ET (boundary belongs to the open session)", () => {
    const s = getMarketSession(utc("2026-06-10T13:30:00Z"));
    expect(s.state).toBe("regular");
    expect(s.nextTransition.toISOString()).toBe("2026-06-10T20:00:00.000Z"); // 16:00 ET
  });

  it("regular at 15:59 ET (last minute before the close)", () => {
    expect(getMarketSession(utc("2026-06-10T19:59:00Z")).state).toBe("regular");
  });

  it("after-hours at exactly 16:00 ET, ends at 20:00 ET", () => {
    const s = getMarketSession(utc("2026-06-10T20:00:00Z")); // 16:00 ET
    expect(s.state).toBe("after");
    expect(s.nextLabel).toBe("after-hours ends");
    expect(s.nextTransition.toISOString()).toBe("2026-06-11T00:00:00.000Z"); // 20:00 ET
  });

  it("closed (overnight) at exactly 20:00 ET — next open is TOMORROW 04:00 ET", () => {
    const s = getMarketSession(utc("2026-06-11T00:00:00Z")); // Wed 20:00 ET
    expect(s.state).toBe("closed");
    expect(s.closedReason).toBe("overnight");
    expect(s.nextTransition.toISOString()).toBe("2026-06-11T08:00:00.000Z"); // Thu 04:00 ET
  });

  it("closed (overnight) at 03:00 ET — next open is TODAY 04:00 ET", () => {
    const s = getMarketSession(utc("2026-06-10T07:00:00Z")); // 03:00 ET
    expect(s.state).toBe("closed");
    expect(s.closedReason).toBe("overnight");
    expect(s.nextTransition.toISOString()).toBe("2026-06-10T08:00:00.000Z"); // 04:00 ET
  });

  it("pre-market at exactly 04:00 ET (boundary belongs to pre-market)", () => {
    expect(getMarketSession(utc("2026-06-10T08:00:00Z")).state).toBe("pre");
  });
});

describe("getMarketSession — weekends", () => {
  it("Saturday noon → closed/weekend, next open Monday 04:00 ET", () => {
    const s = getMarketSession(utc("2026-06-13T16:00:00Z")); // Sat 12:00 ET
    expect(s.state).toBe("closed");
    expect(s.closedReason).toBe("weekend");
    expect(s.nextTransition.toISOString()).toBe("2026-06-15T08:00:00.000Z"); // Mon 04:00 ET
  });

  it("Friday 20:30 ET → closed/overnight, skips the weekend to Monday", () => {
    // WHY 'overnight' (not 'weekend'): the caption answers "why closed NOW" —
    // at 20:30 on Friday the market just closed for the day; the weekend
    // hasn't started on the Eastern calendar yet.
    const s = getMarketSession(utc("2026-06-13T00:30:00Z")); // Fri 06-12 20:30 ET
    expect(s.state).toBe("closed");
    expect(s.closedReason).toBe("overnight");
    expect(s.nextTransition.toISOString()).toBe("2026-06-15T08:00:00.000Z"); // Mon 04:00 ET
  });

  it("Sunday → closed/weekend", () => {
    const s = getMarketSession(utc("2026-06-14T16:00:00Z")); // Sun 12:00 ET
    expect(s.state).toBe("closed");
    expect(s.closedReason).toBe("weekend");
  });
});

describe("getMarketSession — 2026 holidays", () => {
  it("Juneteenth (Fri 2026-06-19) mid-day → closed/holiday, next open Monday", () => {
    const s = getMarketSession(utc("2026-06-19T14:00:00Z")); // Fri 10:00 ET
    expect(s.state).toBe("closed");
    expect(s.closedReason).toBe("holiday");
    // Sat + Sun skipped → Monday 06-22 04:00 ET = 08:00 UTC (EDT).
    expect(s.nextTransition.toISOString()).toBe("2026-06-22T08:00:00.000Z");
  });

  it("Thanksgiving (Thu 2026-11-26, EST) → closed/holiday, next open Friday", () => {
    const s = getMarketSession(utc("2026-11-26T17:00:00Z")); // Thu 12:00 ET
    expect(s.state).toBe("closed");
    expect(s.closedReason).toBe("holiday");
    // Friday 11-27 is a trading day (early-close half day — full-day list only).
    expect(s.nextTransition.toISOString()).toBe("2026-11-27T09:00:00.000Z"); // 04:00 EST
  });
});

describe("getMarketSession — winter time (EST, UTC-5)", () => {
  it("regular session on Mon 2026-01-05 at 10:00 ET", () => {
    const s = getMarketSession(utc("2026-01-05T15:00:00Z")); // 10:00 EST
    expect(s.state).toBe("regular");
    expect(s.nextTransition.toISOString()).toBe("2026-01-05T21:00:00.000Z"); // 16:00 EST
  });
});

describe("formatCountdown", () => {
  it("'now' at or past the transition", () => {
    expect(formatCountdown(0)).toBe("now");
    expect(formatCountdown(-5_000)).toBe("now");
  });
  it("'<1m' inside the final minute", () => {
    expect(formatCountdown(30_000)).toBe("<1m");
    expect(formatCountdown(59_999)).toBe("<1m");
  });
  it("minutes only under an hour (ceil — never shows 0m early)", () => {
    expect(formatCountdown(60_000)).toBe("1m");
    expect(formatCountdown(5 * 60_000)).toBe("5m");
    expect(formatCountdown(5 * 60_000 + 1)).toBe("6m"); // ceil
  });
  it("h+m format under a day", () => {
    expect(formatCountdown(90 * 60_000)).toBe("1h 30m");
    expect(formatCountdown(6 * 3_600_000)).toBe("6h 0m");
  });
  it("d+h format for long weekends", () => {
    expect(formatCountdown(26 * 3_600_000)).toBe("1d 2h");
    expect(formatCountdown(60 * 3_600_000)).toBe("2d 12h");
  });
});

describe("formatNyClock", () => {
  it("renders 24h Eastern wall clock with ET suffix (EDT)", () => {
    expect(formatNyClock(utc("2026-06-10T12:00:00Z"))).toBe("08:00:00 ET");
  });
  it("renders winter offset correctly (EST)", () => {
    expect(formatNyClock(utc("2026-01-05T15:30:05Z"))).toBe("10:30:05 ET");
  });
});

describe("SESSION_LABEL", () => {
  it("covers all four states with terminal-style labels", () => {
    expect(SESSION_LABEL).toEqual({
      pre: "PRE-MARKET",
      regular: "MARKET OPEN",
      after: "AFTER HOURS",
      closed: "CLOSED",
    });
  });
});
