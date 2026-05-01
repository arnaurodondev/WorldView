/**
 * __tests__/parse-shorthand.test.ts — TradingView-style shorthand parser
 *
 * WHY THIS EXISTS: Wave F-2 (PLAN-0059-F): NumberInput accepts user-friendly
 * shorthand. The parser is the foundation; if it gets a single edge case
 * wrong, every NumberInput in the app silently misinterprets values. These
 * tests lock the contract.
 */

import { describe, it, expect } from "vitest";
import { parseShorthand, formatShorthand } from "@/lib/format/parse-shorthand";

describe("parseShorthand", () => {
  describe("plain numbers", () => {
    it("parses a positive integer", () => {
      expect(parseShorthand("100")).toBe(100);
    });
    it("parses a positive decimal", () => {
      expect(parseShorthand("1.5")).toBe(1.5);
    });
    it("parses a negative number", () => {
      expect(parseShorthand("-5.25")).toBe(-5.25);
    });
    it("parses a leading-plus number", () => {
      expect(parseShorthand("+42")).toBe(42);
    });
    it("returns null for empty string", () => {
      expect(parseShorthand("")).toBeNull();
    });
    it("returns null for non-numeric", () => {
      expect(parseShorthand("abc")).toBeNull();
    });
    it("returns null for null/undefined", () => {
      expect(parseShorthand(null)).toBeNull();
      expect(parseShorthand(undefined)).toBeNull();
    });
    it("passes through finite numbers", () => {
      expect(parseShorthand(42)).toBe(42);
    });
    it("returns null for NaN/Infinity", () => {
      expect(parseShorthand(NaN)).toBeNull();
      expect(parseShorthand(Infinity)).toBeNull();
    });
  });

  describe("SI suffixes", () => {
    it("parses k as 1e3", () => {
      expect(parseShorthand("1k")).toBe(1000);
    });
    it("parses m as 1e6 (case-insensitive)", () => {
      expect(parseShorthand("1.5m")).toBe(1_500_000);
      expect(parseShorthand("1.5M")).toBe(1_500_000);
    });
    it("parses b as 1e9", () => {
      expect(parseShorthand("2.3b")).toBe(2_300_000_000);
    });
    it("parses t as 1e12", () => {
      expect(parseShorthand("1.2t")).toBe(1_200_000_000_000);
    });
    it("parses negative SI shorthand", () => {
      expect(parseShorthand("-2.5b")).toBe(-2_500_000_000);
    });
  });

  describe("currency prefixes", () => {
    it("strips $ prefix", () => {
      expect(parseShorthand("$1.5m")).toBe(1_500_000);
    });
    it("strips € prefix", () => {
      expect(parseShorthand("€2.3b")).toBe(2_300_000_000);
    });
    it("strips £ prefix", () => {
      expect(parseShorthand("£100")).toBe(100);
    });
    it("strips ¥ prefix", () => {
      expect(parseShorthand("¥50000")).toBe(50000);
    });
  });

  describe("percent suffix", () => {
    it("returns fraction by default (2% → 0.02)", () => {
      expect(parseShorthand("2%")).toBeCloseTo(0.02);
    });
    it("returns negative fraction (-15% → -0.15)", () => {
      expect(parseShorthand("-15%")).toBeCloseTo(-0.15);
    });
    it("supports +/- prefix on percent", () => {
      expect(parseShorthand("+2%")).toBeCloseTo(0.02);
    });
    it("returns literal when percentAsFraction=false (2% → 2)", () => {
      expect(parseShorthand("2%", { percentAsFraction: false })).toBe(2);
    });
  });

  describe("basis points suffix", () => {
    it("returns fraction by default (25bps → 0.0025)", () => {
      expect(parseShorthand("25bps")).toBeCloseTo(0.0025);
    });
    it("accepts both bp and bps", () => {
      expect(parseShorthand("25bp")).toBeCloseTo(0.0025);
    });
    it("returns literal when bpsAsFraction=false (25bps → 25)", () => {
      expect(parseShorthand("25bps", { bpsAsFraction: false })).toBe(25);
    });
  });

  describe("thousands separators", () => {
    it("strips commas", () => {
      expect(parseShorthand("1,234.56")).toBe(1234.56);
    });
    it("strips spaces", () => {
      expect(parseShorthand("1 234.56")).toBe(1234.56);
    });
    it("strips apostrophes (CH-DE locale)", () => {
      expect(parseShorthand("1'234'567")).toBe(1234567);
    });
  });

  describe("accounting parens negative", () => {
    it("treats (500) as -500", () => {
      expect(parseShorthand("(500)")).toBe(-500);
    });
    it("treats ($1.5m) as -1500000", () => {
      expect(parseShorthand("($1.5m)")).toBe(-1_500_000);
    });
  });

  describe("combinations", () => {
    it("$1.5m → 1500000", () => {
      expect(parseShorthand("$1.5m")).toBe(1_500_000);
    });
    it("trims whitespace", () => {
      expect(parseShorthand("  $1.5m  ")).toBe(1_500_000);
    });
    it("returns null for ambiguous garbage", () => {
      expect(parseShorthand("$$$")).toBeNull();
      expect(parseShorthand("1m2b")).toBeNull(); // "1m2" not parseable
    });
  });
});

describe("formatShorthand", () => {
  it("returns empty string for null", () => {
    expect(formatShorthand(null)).toBe("");
    expect(formatShorthand(undefined)).toBe("");
  });
  it("returns raw number for values < 1000", () => {
    expect(formatShorthand(42)).toBe("42");
    expect(formatShorthand(999)).toBe("999");
  });
  it("formats thousands as K", () => {
    expect(formatShorthand(1500)).toBe("1.5K");
  });
  it("formats millions as M", () => {
    expect(formatShorthand(1_500_000)).toBe("1.5M");
  });
  it("formats billions as B", () => {
    expect(formatShorthand(2_300_000_000)).toBe("2.3B");
  });
  it("formats trillions as T", () => {
    expect(formatShorthand(1_200_000_000_000)).toBe("1.2T");
  });
  it("trims trailing zeros", () => {
    expect(formatShorthand(2_000_000)).toBe("2M");
    expect(formatShorthand(2_500_000_000)).toBe("2.5B");
  });
  it("formats negatives with leading minus", () => {
    expect(formatShorthand(-1_500_000)).toBe("-1.5M");
  });
  it("round-trips parse → format", () => {
    expect(formatShorthand(parseShorthand("2.5b"))).toBe("2.5B");
    expect(formatShorthand(parseShorthand("$850k"))).toBe("850K");
  });
});
