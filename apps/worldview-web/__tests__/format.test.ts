/**
 * __tests__/format.test.ts — PLAN-0059-C C-5 canonical formatters.
 *
 * COVERS the C-5 critical tests:
 *   - test_format_compact_currency_multi_currency
 *     → EUR/GBP/JPY/BTC each render with the correct symbol.
 *   - test_format_basis_points
 *     → returns "+23 bps" / "-12 bps".
 */

import { describe, it, expect } from "vitest";
import {
  formatCompact,
  formatCompactCurrency,
  formatPrice,
  formatBasisPoints,
  formatPercent,
  formatPercentUnsigned,
  formatRatio,
} from "@/lib/format";

describe("formatCompact (default — fixed 2 decimals, K is integer)", () => {
  it("formats millions / billions / trillions", () => {
    expect(formatCompact(1_234_567)).toBe("1.23M");
    expect(formatCompact(2_450_000_000)).toBe("2.45B");
    expect(formatCompact(987_654_321)).toBe("987.65M");
    expect(formatCompact(2_450_000_000_000)).toBe("2.45T");
  });

  it("uses K suffix with 0 decimals (legacy behaviour)", () => {
    expect(formatCompact(5432)).toBe("5K");
  });

  it("handles negatives", () => {
    expect(formatCompact(-2_450_000)).toBe("-2.45M");
  });

  it("returns dash for null / undefined / NaN", () => {
    expect(formatCompact(null)).toBe("—");
    expect(formatCompact(undefined)).toBe("—");
    expect(formatCompact(NaN)).toBe("—");
  });

  it("adaptive: true reduces decimals as scaled value grows", () => {
    expect(formatCompact(987_654_321, { adaptive: true })).toBe("988M");
    expect(formatCompact(23_456_789, { adaptive: true })).toBe("23.5M");
    expect(formatCompact(2_345_678, { adaptive: true })).toBe("2.35M");
  });
});

describe("formatCompactCurrency — multi-currency", () => {
  it("uses $ for USD", () => {
    expect(formatCompactCurrency(2_450_000_000)).toBe("$2.45B");
  });

  it("uses € for EUR", () => {
    expect(formatCompactCurrency(2_450_000_000, "EUR")).toBe("€2.45B");
  });

  it("uses £ for GBP", () => {
    expect(formatCompactCurrency(450_000_000, "GBP")).toBe("£450.00M");
  });

  it("uses ¥ for JPY", () => {
    expect(formatCompactCurrency(123_000_000, "JPY")).toBe("¥123.00M");
  });

  it("uses ₿ for BTC small amounts (no compact)", () => {
    // Below 1M → falls through to formatPrice. BTC isn't recognised by Intl
    // so the hand-assembled fallback runs and emits "₿0.0234".
    const out = formatCompactCurrency(0.0234, "BTC");
    expect(out.startsWith("₿")).toBe(true);
    expect(out).toContain("0.0234");
  });

  it("handles negative billions with sign before symbol", () => {
    expect(formatCompactCurrency(-2_450_000_000)).toBe("-$2.45B");
  });

  it("keeps the legacy $1M boundary by default (sub-million → full price)", () => {
    expect(formatCompactCurrency(100_000)).toBe("$100,000.00");
  });

  it("compacts from $1K when compactThreshold is lowered (tight-space callers)", () => {
    expect(formatCompactCurrency(100_000, "USD", { compactThreshold: 1_000, maxDecimals: 1 })).toBe("$100.0K");
    expect(formatCompactCurrency(50_000, "USD", { compactThreshold: 1_000, maxDecimals: 1 })).toBe("$50.0K");
    // Below the lowered threshold still renders as a full grouped price.
    expect(formatCompactCurrency(842, "USD", { compactThreshold: 1_000 })).toBe("$842.00");
  });
});

describe("formatPrice — locale grouping", () => {
  it("formats simple price with $", () => {
    expect(formatPrice(182.34)).toBe("$182.34");
  });

  it("uses thousands separator", () => {
    expect(formatPrice(4892.11)).toBe("$4,892.11");
  });

  it("formats negative", () => {
    expect(formatPrice(-25.5)).toBe("-$25.50");
  });
});

describe("formatBasisPoints", () => {
  it("returns +23 bps for 0.0023", () => {
    expect(formatBasisPoints(0.0023)).toBe("+23 bps");
  });

  it("returns -12 bps for -0.0012", () => {
    expect(formatBasisPoints(-0.0012)).toBe("-12 bps");
  });

  it("returns +0.0 bps for zero", () => {
    expect(formatBasisPoints(0)).toBe("+0.0 bps");
  });

  it("shows one decimal for sub-bp values", () => {
    expect(formatBasisPoints(0.00005)).toBe("+0.5 bps");
  });

  it("returns dash for null", () => {
    expect(formatBasisPoints(null)).toBe("—");
  });
});

describe("formatPercent / formatPercentUnsigned / formatRatio", () => {
  it("formatPercent adds + for positive", () => {
    expect(formatPercent(0.0234)).toBe("+2.34%");
  });

  it("formatPercent shows - for negative", () => {
    expect(formatPercent(-0.0112)).toBe("-1.12%");
  });

  it("formatPercentUnsigned has no sign", () => {
    expect(formatPercentUnsigned(1)).toBe("100.00%");
  });

  it("formatRatio adds x suffix", () => {
    expect(formatRatio(24.567)).toBe("24.57x");
  });
});
