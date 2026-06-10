/**
 * features/portfolio/lib/__tests__/sector-filter.test.ts (R2 sprint)
 *
 * WHY: the donut's sector labels (S9 sector-breakdown → instruments.sector)
 * and the table's per-holding sectors (holding overviews) travel different
 * data paths; this lib is the single matching contract between them. These
 * tests pin the case-insensitivity + "Unknown" bucket rules.
 */

import { describe, it, expect } from "vitest";

import {
  holdingMatchesSector,
  filterHoldingsBySector,
  UNKNOWN_SECTOR,
} from "../sector-filter";
import type { Holding } from "@/types/api";

// ── Fixtures ──────────────────────────────────────────────────────────────────

function makeHolding(id: string, ticker: string): Holding {
  return {
    holding_id: `h-${id}`,
    portfolio_id: "p-1",
    instrument_id: id,
    entity_id: `e-${id}`,
    ticker,
    name: ticker,
    quantity: 1,
    average_cost: 100,
    current_price: null,
    unrealised_pnl: null,
    unrealised_pnl_pct: null,
    portfolio_weight: null,
  };
}

const HOLDINGS = [
  makeHolding("i-aapl", "AAPL"),
  makeHolding("i-xom", "XOM"),
  makeHolding("i-mystery", "MYST"),
];

const SECTORS: Record<string, string | null> = {
  "i-aapl": "Information Technology",
  "i-xom": "Energy",
  "i-mystery": null, // unclassified — lives in the "Unknown" bucket
};

// ── holdingMatchesSector ──────────────────────────────────────────────────────

describe("holdingMatchesSector", () => {
  it("matches exact sector names", () => {
    expect(holdingMatchesSector("Energy", "Energy")).toBe(true);
    expect(holdingMatchesSector("Energy", "Financials")).toBe(false);
  });

  it("is case-insensitive and trims whitespace (cross-data-path drift)", () => {
    expect(holdingMatchesSector("health care", "Health Care")).toBe(true);
    expect(holdingMatchesSector(" Energy ", "energy")).toBe(true);
  });

  it("bridges the EODHD↔GICS taxonomy split (verified live 2026-06-10)", () => {
    // Donut filter = EODHD name (from /sector-breakdown via instruments.sector);
    // holding sector = GICS name (from the company-overview batch). These
    // pairs were observed on the live dev stack — exact equality matched 0
    // rows before the alias table existed.
    expect(holdingMatchesSector("Information Technology", "Technology")).toBe(true);
    expect(holdingMatchesSector("Consumer Discretionary", "Consumer Cyclical")).toBe(true);
    expect(holdingMatchesSector("Consumer Staples", "Consumer Defensive")).toBe(true);
    expect(holdingMatchesSector("Financials", "Financial Services")).toBe(true);
    expect(holdingMatchesSector("Health Care", "Healthcare")).toBe(true);
    expect(holdingMatchesSector("Materials", "Basic Materials")).toBe(true);
    // And symmetrically (the filter could come from either taxonomy).
    expect(holdingMatchesSector("Technology", "Information Technology")).toBe(true);
    // Aliasing must NOT create false positives across distinct sectors.
    expect(holdingMatchesSector("Information Technology", "Consumer Cyclical")).toBe(false);
    expect(holdingMatchesSector("Energy", "Technology")).toBe(false);
  });

  it("null/empty holding sector matches ONLY the Unknown bucket", () => {
    expect(holdingMatchesSector(null, UNKNOWN_SECTOR)).toBe(true);
    expect(holdingMatchesSector(undefined, "unknown")).toBe(true);
    expect(holdingMatchesSector("", UNKNOWN_SECTOR)).toBe(true);
    expect(holdingMatchesSector(null, "Energy")).toBe(false);
  });
});

// ── filterHoldingsBySector ────────────────────────────────────────────────────

describe("filterHoldingsBySector", () => {
  it("returns the SAME array reference when no filter (referential stability)", () => {
    expect(filterHoldingsBySector(HOLDINGS, SECTORS, null)).toBe(HOLDINGS);
    expect(filterHoldingsBySector(HOLDINGS, SECTORS, "")).toBe(HOLDINGS);
  });

  it("keeps only rows in the requested sector", () => {
    const out = filterHoldingsBySector(HOLDINGS, SECTORS, "Energy");
    expect(out.map((h) => h.ticker)).toEqual(["XOM"]);
  });

  it("'Unknown' selects the unclassified rows", () => {
    const out = filterHoldingsBySector(HOLDINGS, SECTORS, UNKNOWN_SECTOR);
    expect(out.map((h) => h.ticker)).toEqual(["MYST"]);
  });

  it("a sector matching nothing yields an empty array (named UI state)", () => {
    expect(filterHoldingsBySector(HOLDINGS, SECTORS, "Utilities")).toEqual([]);
  });
});
