/**
 * __tests__/market-schedule.test.ts — Unit tests for market hours computation
 *
 * WHY THIS EXISTS: computeMarketStatus() is a pure function that determines
 * whether to show green/amber/red in the TopBar. Tests verify correctness
 * for the times that matter most: market opens, market closes, lunch breaks.
 *
 * WHY pure function tests (no mocking): computeMarketStatus() takes a Date and
 * returns a result — no imports to mock, no side effects. Perfect for unit testing.
 */

import { describe, it, expect } from "vitest";
import { computeMarketStatus } from "@/lib/market-schedule";

/**
 * utcDate — create a UTC Date for a specific day and time
 * WHY helper: avoids repeating `new Date(Date.UTC(...))` in every test
 */
function utcDate(
  year: number,
  month: number, // 1-12
  day: number,
  hour: number,
  minute: number = 0,
): Date {
  return new Date(Date.UTC(year, month - 1, day, hour, minute));
}

// Use a fixed Monday date (Monday 2026-04-20) to avoid weekday/weekend issues
const MONDAY = 20;
const TUESDAY = 21;
const SATURDAY = 25; // Saturday 2026-04-25
const SUNDAY = 19;   // Sunday 2026-04-19
const YEAR = 2026;
const MONTH = 4;

describe("computeMarketStatus — NYSE/NASDAQ", () => {
  it("returns open during regular session (15:00 UTC Mon)", () => {
    const result = computeMarketStatus(utcDate(YEAR, MONTH, MONDAY, 15, 0));
    const nyse = result.exchanges.find((e) => e.name === "NYSE / NASDAQ")!;
    expect(nyse.status).toBe("open");
    expect(result.overall).toBe("open");
  });

  it("returns pre-market before regular session (12:00 UTC Mon)", () => {
    const result = computeMarketStatus(utcDate(YEAR, MONTH, MONDAY, 12, 0));
    const nyse = result.exchanges.find((e) => e.name === "NYSE / NASDAQ")!;
    expect(nyse.status).toBe("pre-market");
    expect(result.overall).toBe("pre-after-hours");
  });

  it("returns after-hours after regular session (22:00 UTC Mon)", () => {
    const result = computeMarketStatus(utcDate(YEAR, MONTH, MONDAY, 22, 0));
    const nyse = result.exchanges.find((e) => e.name === "NYSE / NASDAQ")!;
    expect(nyse.status).toBe("after-hours");
    expect(result.overall).toBe("pre-after-hours");
  });

  it("returns closed on Saturday", () => {
    const result = computeMarketStatus(utcDate(YEAR, MONTH, SATURDAY, 15, 0));
    const nyse = result.exchanges.find((e) => e.name === "NYSE / NASDAQ")!;
    expect(nyse.status).toBe("closed");
  });

  it("returns closed before pre-market (06:00 UTC Mon)", () => {
    const result = computeMarketStatus(utcDate(YEAR, MONTH, MONDAY, 6, 0));
    const nyse = result.exchanges.find((e) => e.name === "NYSE / NASDAQ")!;
    expect(nyse.status).toBe("closed");
  });
});

describe("computeMarketStatus — LSE (London)", () => {
  it("returns open during session (10:00 UTC Mon)", () => {
    const result = computeMarketStatus(utcDate(YEAR, MONTH, MONDAY, 10, 0));
    const lse = result.exchanges.find((e) => e.name.includes("LSE"))!;
    expect(lse.status).toBe("open");
  });

  it("returns closed before open (07:00 UTC Mon)", () => {
    const result = computeMarketStatus(utcDate(YEAR, MONTH, MONDAY, 7, 0));
    const lse = result.exchanges.find((e) => e.name.includes("LSE"))!;
    expect(lse.status).toBe("closed");
  });

  it("returns closed after close (17:00 UTC Mon)", () => {
    const result = computeMarketStatus(utcDate(YEAR, MONTH, MONDAY, 17, 0));
    const lse = result.exchanges.find((e) => e.name.includes("LSE"))!;
    expect(lse.status).toBe("closed");
  });
});

describe("computeMarketStatus — TSE (Tokyo, lunch break)", () => {
  it("returns open in morning session (01:00 UTC Mon)", () => {
    const result = computeMarketStatus(utcDate(YEAR, MONTH, MONDAY, 1, 0));
    const tse = result.exchanges.find((e) => e.name.includes("TSE"))!;
    expect(tse.status).toBe("open");
  });

  it("returns closed during lunch break (03:00 UTC Mon)", () => {
    const result = computeMarketStatus(utcDate(YEAR, MONTH, MONDAY, 3, 0));
    const tse = result.exchanges.find((e) => e.name.includes("TSE"))!;
    expect(tse.status).toBe("closed");
  });

  it("returns open in afternoon session (04:00 UTC Mon)", () => {
    const result = computeMarketStatus(utcDate(YEAR, MONTH, MONDAY, 4, 0));
    const tse = result.exchanges.find((e) => e.name.includes("TSE"))!;
    expect(tse.status).toBe("open");
  });
});

describe("computeMarketStatus — Crypto", () => {
  it("is always open (Saturday midnight)", () => {
    const result = computeMarketStatus(utcDate(YEAR, MONTH, SATURDAY, 0, 0));
    const crypto = result.exchanges.find((e) => e.name === "Crypto")!;
    expect(crypto.status).toBe("open");
  });

  it("is always open (weekday business hours)", () => {
    const result = computeMarketStatus(utcDate(YEAR, MONTH, MONDAY, 15, 0));
    const crypto = result.exchanges.find((e) => e.name === "Crypto")!;
    expect(crypto.status).toBe("open");
  });
});

describe("computeMarketStatus — overall status", () => {
  it("overall is closed on Saturday when no equity open", () => {
    // Saturday 15:00 UTC — NYSE closed, LSE closed, TSE closed, HKEX closed, Euronext closed
    const result = computeMarketStatus(utcDate(YEAR, MONTH, SATURDAY, 15, 0));
    expect(result.overall).toBe("closed");
  });

  it("overall is open when LSE is open on weekday morning", () => {
    // Monday 09:00 UTC — LSE open, NYSE not yet
    const result = computeMarketStatus(utcDate(YEAR, MONTH, MONDAY, 9, 0));
    expect(result.overall).toBe("open");
  });

  it("overall is pre-after-hours during NYSE extended hours only", () => {
    // Monday 22:00 UTC — all equity markets closed except NYSE after-hours
    const result = computeMarketStatus(utcDate(YEAR, MONTH, MONDAY, 22, 0));
    expect(result.overall).toBe("pre-after-hours");
  });

  it("returns exactly 8 exchanges", () => {
    const result = computeMarketStatus(utcDate(YEAR, MONTH, MONDAY, 15, 0));
    expect(result.exchanges).toHaveLength(8);
  });
});
