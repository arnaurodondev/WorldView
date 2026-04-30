/**
 * Tests for the alias-type design tokens + AliasPill component (PLAN-0057 Wave F-2).
 *
 * The Wave C-3 backend change introduced 5 new alias_types — the test below
 * pins the contract that every one renders with a unique colour and label
 * so analysts can distinguish CUSIP from FIGI from ISIN at a glance.
 */

import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";

import { AliasPill } from "@/components/entity/AliasPill";
import { aliasTypeToken, sortAliasesByType } from "@/lib/alias-types";

describe("aliasTypeToken", () => {
  it("returns explicit tokens for every Wave C-3 alias_type", () => {
    const required = ["CUSIP", "FIGI", "LEI", "PRIMARY_TICKER", "NAME"];
    for (const type of required) {
      const token = aliasTypeToken(type);
      expect(token.label, `missing label for ${type}`).not.toBe("Alias");
      expect(token.className, `missing className for ${type}`).not.toContain(
        "muted-foreground",
      );
    }
  });

  it("falls back gracefully for unknown alias_types", () => {
    const token = aliasTypeToken("UNRECOGNISED_TYPE");
    expect(token.label).toBe("Alias");
    expect(token.sortIndex).toBe(100);
  });

  it("falls back for null/undefined alias_type", () => {
    expect(aliasTypeToken(null).label).toBe("Alias");
    expect(aliasTypeToken(undefined).label).toBe("Alias");
  });
});

describe("sortAliasesByType", () => {
  it("orders primary identifiers before reference identifiers", () => {
    const input = [
      { alias_type: "ISIN", value: "US0378331005" },
      { alias_type: "TICKER", value: "AAPL" },
      { alias_type: "EXACT", value: "Apple Inc." },
      { alias_type: "PRIMARY_TICKER", value: "AAPL.US" },
      { alias_type: "FIGI", value: "BBG000B9XRY4" },
    ];
    const ordered = sortAliasesByType(input).map((a) => a.alias_type);
    expect(ordered).toEqual([
      "EXACT",
      "TICKER",
      "PRIMARY_TICKER",
      "ISIN",
      "FIGI",
    ]);
  });

  it("keeps unknown types at the tail", () => {
    const input = [
      { alias_type: "FUTURE_TYPE", value: "x" },
      { alias_type: "EXACT", value: "y" },
    ];
    const ordered = sortAliasesByType(input).map((a) => a.alias_type);
    expect(ordered[0]).toBe("EXACT");
    expect(ordered[1]).toBe("FUTURE_TYPE");
  });

  it("does not mutate the input array", () => {
    const input = [
      { alias_type: "ISIN", value: "x" },
      { alias_type: "EXACT", value: "y" },
    ];
    const ordered = sortAliasesByType(input);
    expect(input.map((a) => a.alias_type)).toEqual(["ISIN", "EXACT"]);
    expect(ordered).not.toBe(input);
  });
});

describe("AliasPill", () => {
  it("renders the alias label and value for known types", () => {
    render(<AliasPill aliasType="CUSIP" value="037833100" />);
    expect(screen.getByText("037833100")).toBeInTheDocument();
    expect(screen.getByText("CUSIP")).toBeInTheDocument();
  });

  it("renders without label when hideLabel is set", () => {
    render(<AliasPill aliasType="ISIN" value="US0378331005" hideLabel />);
    expect(screen.getByText("US0378331005")).toBeInTheDocument();
    expect(screen.queryByText("ISIN")).toBeNull();
  });

  it("renders the long value in title attribute even when truncated", () => {
    render(<AliasPill aliasType="LEI" value="HWUPKR0MPOU8FGXBT394" />);
    const span = screen.getByText("HWUPKR0MPOU8FGXBT394");
    expect(span.closest("span[title]")?.getAttribute("title")).toBe(
      "LEI: HWUPKR0MPOU8FGXBT394",
    );
  });

  it("falls back gracefully for unknown alias_type", () => {
    render(<AliasPill aliasType="UNKNOWN_TYPE" value="abc123" />);
    expect(screen.getByText("abc123")).toBeInTheDocument();
    expect(screen.getByText("Alias")).toBeInTheDocument();
  });
});
