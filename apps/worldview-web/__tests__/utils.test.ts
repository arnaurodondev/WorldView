/**
 * __tests__/utils.test.ts — Unit tests for lib/utils.ts formatters
 *
 * WHY THESE TESTS EXIST: Financial formatters are the most critical utility
 * functions in the app. A wrong decimal place, wrong sign prefix, or wrong
 * compact notation would directly confuse professional finance users.
 * Tests verify Bloomberg-standard formatting for every function.
 */

import { describe, it, expect } from "vitest";
import {
  cn,
  formatPrice,
  formatPriceCompact,
  formatPercent,
  formatPercentDirect,
  formatVolume,
  formatMarketCap,
  formatRatio,
  formatRelativeTime,
  priceChangeClass,
  heatCellColor,
  severityColor,
  truncate,
  // POLISH PASS 2026-05-09: regression-lock the Invalid-Date guards added to
  // formatDate, formatDateTime, and the new safeFormatClockTime helper. The
  // production bug we are guarding against was the literal string "Invalid
  // Date" appearing in chat bubbles + table cells when the upstream payload
  // had a null / "" / non-ISO `created_at`.
  formatDate,
  formatDateTime,
  safeFormatClockTime,
} from "@/lib/utils";

// ── cn() ─────────────────────────────────────────────────────────────────────

describe("cn()", () => {
  it("merges class strings", () => {
    expect(cn("a", "b")).toBe("a b");
  });

  it("resolves Tailwind conflicts — last class wins", () => {
    // Without tailwind-merge: both would appear; with merge: last wins
    expect(cn("text-red-500", "text-green-500")).toBe("text-green-500");
  });

  it("filters falsy values", () => {
    expect(cn("a", false && "b", undefined, null, "c")).toBe("a c");
  });
});

// ── formatPrice() ─────────────────────────────────────────────────────────

describe("formatPrice()", () => {
  it("formats standard price with 2 decimals", () => {
    expect(formatPrice(182.34)).toBe("$182.34");
  });

  it("formats price with cents", () => {
    expect(formatPrice(0.05)).toBe("$0.05");
  });

  it("formats large price with thousands separator", () => {
    expect(formatPrice(4892.11)).toBe("$4,892.11");
  });

  it("returns dash for null", () => {
    expect(formatPrice(null)).toBe("—");
  });

  it("returns dash for undefined", () => {
    expect(formatPrice(undefined)).toBe("—");
  });
});

// ── formatPriceCompact() ─────────────────────────────────────────────────

describe("formatPriceCompact()", () => {
  it("uses M suffix for million range", () => {
    expect(formatPriceCompact(1_500_000)).toBe("$1.50M");
  });

  it("uses B suffix for billion range", () => {
    expect(formatPriceCompact(2_450_000_000)).toBe("$2.45B");
  });

  it("uses standard format below 1M", () => {
    expect(formatPriceCompact(4892.11)).toBe("$4,892.11");
  });
});

// ── formatPercent() ──────────────────────────────────────────────────────

describe("formatPercent()", () => {
  it("adds + prefix for positive", () => {
    expect(formatPercent(0.0234)).toBe("+2.34%");
  });

  it("shows - prefix for negative", () => {
    expect(formatPercent(-0.0112)).toBe("-1.12%");
  });

  it("shows + prefix for zero", () => {
    expect(formatPercent(0)).toBe("+0.00%");
  });

  it("returns dash for null", () => {
    expect(formatPercent(null)).toBe("—");
  });
});

// ── formatPercentDirect() ────────────────────────────────────────────────

describe("formatPercentDirect()", () => {
  it("formats when value is already in percentage form", () => {
    expect(formatPercentDirect(2.34)).toBe("+2.34%");
    expect(formatPercentDirect(-1.12)).toBe("-1.12%");
  });
});

// ── formatVolume() ───────────────────────────────────────────────────────

describe("formatVolume()", () => {
  it("formats millions", () => {
    expect(formatVolume(1_234_567)).toBe("1.23M");
  });

  it("formats billions", () => {
    expect(formatVolume(987_654_321)).toBe("987.65M");
  });

  it("formats thousands", () => {
    expect(formatVolume(5_432)).toBe("5K");
  });

  it("returns dash for null", () => {
    expect(formatVolume(null)).toBe("—");
  });
});

// ── formatMarketCap() ────────────────────────────────────────────────────

describe("formatMarketCap()", () => {
  it("formats trillions", () => {
    expect(formatMarketCap(2_450_000_000_000)).toBe("$2.45T");
  });

  it("formats billions", () => {
    expect(formatMarketCap(500_000_000_000)).toBe("$500.00B");
  });
});

// ── formatRatio() ────────────────────────────────────────────────────────

describe("formatRatio()", () => {
  it("formats PE ratio with x suffix", () => {
    expect(formatRatio(24.567)).toBe("24.57x");
  });

  it("returns dash for null", () => {
    expect(formatRatio(null)).toBe("—");
  });
});

// ── priceChangeClass() ───────────────────────────────────────────────────

describe("priceChangeClass()", () => {
  it("returns positive class for positive value", () => {
    expect(priceChangeClass(1.5)).toBe("text-positive");
  });

  it("returns negative class for negative value", () => {
    expect(priceChangeClass(-0.5)).toBe("text-negative");
  });

  it("returns neutral class for zero", () => {
    expect(priceChangeClass(0)).toBe("text-muted-foreground");
  });

  it("returns neutral class for null", () => {
    expect(priceChangeClass(null)).toBe("text-muted-foreground");
  });
});

// ── heatCellColor() ─────────────────────────────────────────────────────
//
// PLAN-0059 W0 F-VISUAL-003 fix: heatCellColor() now derives all colors from
// CSS variables (hsl(var(--positive))) instead of hardcoded hex literals from
// the retired Bloomberg Dark palette. Test assertions updated accordingly:
//   - Old: #26A69A (TradingView teal), #EF5350 (Material Red 400), #1A2030 (blue-tinted)
//   - New: hsl(var(--positive)), hsl(var(--negative)), hsl(var(--surface-2))
// The CSS-variable form is canonical now — at runtime it resolves to whichever
// values the active theme defines (after PLAN-0059 W0 token surgery: institutional
// green #00D26A and urgent red #FF3B5C). See app/globals.css and lib/utils.ts.

describe("heatCellColor()", () => {
  it("returns neutral surface-2 background for zero change (no longer blue-tinted)", () => {
    const result = heatCellColor(0);
    expect(result.background).toBe("hsl(var(--surface-2))");
    expect(result.color).toBe("hsl(var(--muted-foreground))");
  });

  it("uses --positive token color for large gain (institutional green at runtime)", () => {
    const result = heatCellColor(3);
    expect(result.color).toBe("hsl(var(--positive))");
    // Background uses 32% alpha at the strongest step — verifies the 7-step scale top tier
    expect(result.background).toBe("hsl(var(--positive) / 0.32)");
  });

  it("uses --negative token color for large loss (urgent red at runtime)", () => {
    const result = heatCellColor(-3);
    expect(result.color).toBe("hsl(var(--negative))");
    expect(result.background).toBe("hsl(var(--negative) / 0.32)");
  });

  it("returns surface-2 neutral for null (no data)", () => {
    const result = heatCellColor(null);
    expect(result.background).toBe("hsl(var(--surface-2))");
    expect(result.color).toBe("hsl(var(--muted-foreground))");
  });

  it("never returns retired Bloomberg Dark palette hex values", () => {
    // PLAN-0059 W0 regression guard — these hex literals were forbidden by
    // app/globals.css:11 but the function held them until this fix.
    const FORBIDDEN_HEX = [
      "#1A2030",
      "#0A2E28",
      "#0A2420",
      "#0E201C",
      "#251218",
      "#300E12",
      "#3D0A0E",
      "#26A69A", // TradingView teal — replaced by --positive
      "#EF5350", // Material Red 400 — replaced by --negative
      "#4DB6AC",
      "#6B7585",
      "#EF9A9A",
    ];
    for (const pct of [-3, -2, -1, 0, 1, 2, 3]) {
      const result = heatCellColor(pct);
      for (const hex of FORBIDDEN_HEX) {
        expect(result.background.toUpperCase()).not.toContain(hex.toUpperCase());
        expect(result.color.toUpperCase()).not.toContain(hex.toUpperCase());
      }
    }
  });
});

// ── severityColor() ─────────────────────────────────────────────────────

describe("severityColor()", () => {
  it("returns destructive styling for CRITICAL", () => {
    const result = severityColor("CRITICAL");
    expect(result.text).toBe("text-negative");
  });

  it("returns warning styling for HIGH", () => {
    const result = severityColor("HIGH");
    expect(result.text).toBe("text-warning");
  });
});

// ── truncate() ──────────────────────────────────────────────────────────

describe("truncate()", () => {
  it("returns original when under limit", () => {
    expect(truncate("short", 10)).toBe("short");
  });

  it("truncates and adds ellipsis when over limit", () => {
    expect(truncate("longer than limit", 10)).toBe("longer ...");
  });
});

// ── formatRelativeTime() ────────────────────────────────────────────────

describe("formatRelativeTime()", () => {
  it("returns 'just now' for recent timestamps", () => {
    const recent = new Date(Date.now() - 30_000).toISOString();
    expect(formatRelativeTime(recent)).toBe("just now");
  });

  it("returns minutes for 5 minutes ago", () => {
    const fiveMinutesAgo = new Date(Date.now() - 5 * 60_000).toISOString();
    expect(formatRelativeTime(fiveMinutesAgo)).toBe("5m ago");
  });

  it("returns hours for 2 hours ago", () => {
    const twoHoursAgo = new Date(Date.now() - 2 * 3600_000).toISOString();
    expect(formatRelativeTime(twoHoursAgo)).toBe("2h ago");
  });

  it("returns dash for null", () => {
    expect(formatRelativeTime(null)).toBe("—");
  });
});

// ── formatDate() / formatDateTime() / safeFormatClockTime() ─────────────
//
// POLISH PASS 2026-05-09: Invalid-Date regression guard. These tests fail if
// anyone removes the `Number.isNaN(d.getTime())` short-circuit and the
// formatter once again leaks the literal browser string "Invalid Date" into
// the UI (the bug pattern that motivated this polish pass).

describe("formatDate() — Invalid-Date guard", () => {
  it("returns em-dash for null", () => {
    expect(formatDate(null)).toBe("—");
  });

  it("returns em-dash for undefined", () => {
    expect(formatDate(undefined)).toBe("—");
  });

  it("returns em-dash for empty string (not the literal 'Invalid Date')", () => {
    // Empty string is the most common silent-bug path: `new Date("")` is an
    // Invalid Date but `Intl.DateTimeFormat.format(...)` of one returns the
    // literal 6-char string "Invalid Date" — visible to the user.
    expect(formatDate("")).toBe("—");
  });

  it("returns em-dash for nonsense string", () => {
    expect(formatDate("not-a-date")).toBe("—");
  });

  it("formats a real ISO date", () => {
    // Sanity check — the guard must not regress the happy path.
    expect(formatDate("2026-04-17T14:32:00Z")).toBe("Apr 17, 2026");
  });
});

describe("formatDateTime() — Invalid-Date guard", () => {
  it("returns em-dash for null/undefined/empty", () => {
    expect(formatDateTime(null)).toBe("—");
    expect(formatDateTime(undefined)).toBe("—");
    expect(formatDateTime("")).toBe("—");
  });

  it("returns em-dash for nonsense string", () => {
    expect(formatDateTime("not-a-date")).toBe("—");
  });

  it("formats a real ISO datetime in UTC", () => {
    expect(formatDateTime("2026-04-17T14:32:00Z")).toBe("Apr 17, 14:32 UTC");
  });
});

describe("safeFormatClockTime() — chat-bubble timestamp helper", () => {
  it("returns em-dash for null/undefined/empty", () => {
    expect(safeFormatClockTime(null)).toBe("—");
    expect(safeFormatClockTime(undefined)).toBe("—");
    expect(safeFormatClockTime("")).toBe("—");
  });

  it("returns em-dash for nonsense string (regression guard)", () => {
    // The whole point of this helper: chat bubbles previously rendered the
    // literal "Invalid Date" when message.created_at was null on optimistic
    // sends. We must NEVER see that string again.
    expect(safeFormatClockTime("not-a-date")).toBe("—");
    expect(safeFormatClockTime("not-a-date")).not.toBe("Invalid Date");
  });

  it("formats a real ISO time", () => {
    // We don't pin the exact wall-clock string because toLocaleTimeString is
    // locale-dependent — but it must be non-empty and non-error.
    const out = safeFormatClockTime("2026-04-17T14:32:00Z");
    expect(out).not.toBe("—");
    expect(out).not.toBe("Invalid Date");
    expect(out.length).toBeGreaterThan(0);
  });
});
