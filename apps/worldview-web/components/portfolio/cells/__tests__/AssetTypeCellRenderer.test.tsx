/**
 * components/portfolio/cells/__tests__/AssetTypeCellRenderer.test.tsx
 *
 * WHY THIS EXISTS: Regression guard for the PLAN-0108 T-4-03 chip-label audit.
 * The component was previously rendering 2-3 char codes (EQ/BND/CRY) instead
 * of the single-letter chips (E/F/B/C) mandated by PRD-0108 §T-4-03. These
 * tests lock in the correct labels so future refactors cannot silently regress.
 *
 * WHAT IS TESTED:
 *  - Single-letter chip text for the four first-class asset types (equity/fund/bond/crypto)
 *  - Em-dash fallback for unknown / null / missing asset class
 *  - "etf" alias maps to "F" (backward-compat for legacy rows)
 *  - Pinned bottom row renders "—" (TOTAL footer must not show a chip)
 *
 * WHY params are built by hand (not via AG Grid AgGridReact): the renderer is a
 * plain function — it receives an ICellRendererParams-shaped object and returns
 * JSX. We construct a minimal params stub; the AG Grid library itself is never
 * instantiated so no AgGridReact mock is required beyond the global setup.
 *
 * WHY `instrument_id = "instr-1"` in every params stub: the renderer looks up
 * context.assetClasses[instrument_id] to retrieve the asset class. Any stable
 * string works here; we keep one constant to avoid typos across tests.
 */

import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import type { ICellRendererParams } from "ag-grid-community";
import { AssetTypeCellRenderer } from "@/components/portfolio/cells/AssetTypeCellRenderer";
import type { EnrichedHoldingRow } from "@/components/portfolio/holdings-columns";

// ── Helpers ────────────────────────────────────────────────────────────────────

const INSTRUMENT_ID = "instr-1";

/**
 * buildParams — constructs a minimal ICellRendererParams stub.
 *
 * WHY partial cast: ICellRendererParams has dozens of AG Grid internal fields
 * (eGridCell, api, columnApi, …) that the renderer never touches. Casting a
 * partial object avoids hundreds of lines of boilerplate while still satisfying
 * TypeScript for the fields the renderer actually reads.
 *
 * @param assetClass  The value stored in context.assetClasses[INSTRUMENT_ID].
 *                    Pass undefined to simulate a missing context map entry.
 * @param pinned      When "bottom" the renderer should show "—" (footer row).
 */
function buildParams(
  assetClass: string | null | undefined,
  pinned?: "bottom",
): ICellRendererParams<EnrichedHoldingRow> {
  return {
    // data: the EnrichedHoldingRow for this cell. Only .h.instrument_id is read.
    data: {
      h: { instrument_id: INSTRUMENT_ID } as EnrichedHoldingRow["h"],
    } as EnrichedHoldingRow,

    // node: AG Grid IRowNode. The renderer reads node.rowPinned for the footer guard.
    node: {
      rowPinned: pinned ?? null,
    },

    // context: the AssetTypeContext injected by SemanticHoldingsTable.
    // When assetClass is undefined we omit the key so the lookup returns undefined.
    context:
      assetClass !== undefined
        ? { assetClasses: { [INSTRUMENT_ID]: assetClass } }
        : { assetClasses: {} },
  } as unknown as ICellRendererParams<EnrichedHoldingRow>;
}

// ── Tests ──────────────────────────────────────────────────────────────────────

describe("AssetTypeCellRenderer", () => {
  it("renders E chip for equity", () => {
    // WHY: "equity" is the most common holding type; its chip letter must be "E".
    render(<AssetTypeCellRenderer {...buildParams("equity")} />);
    expect(screen.getByText("E")).toBeInTheDocument();
  });

  it("renders F chip for fund", () => {
    // WHY: "fund" is the PRD-0108 canonical type for mutual funds and ETFs.
    // Single-letter "F" was introduced in T-4-03 to replace the legacy "ETF" label.
    render(<AssetTypeCellRenderer {...buildParams("fund")} />);
    expect(screen.getByText("F")).toBeInTheDocument();
  });

  it("renders F chip for etf (backward-compat alias)", () => {
    // WHY: rows created before the PRD-0108 rename still have assetClass="etf".
    // Both "fund" and "etf" must render "F" so the column is consistent.
    render(<AssetTypeCellRenderer {...buildParams("etf")} />);
    expect(screen.getByText("F")).toBeInTheDocument();
  });

  it("renders B chip for bond", () => {
    // WHY: fixed-income instruments use "bond"; their chip must be "B".
    render(<AssetTypeCellRenderer {...buildParams("bond")} />);
    expect(screen.getByText("B")).toBeInTheDocument();
  });

  it("renders C chip for crypto", () => {
    // WHY: digital assets use "crypto"; their chip must be "C".
    render(<AssetTypeCellRenderer {...buildParams("crypto")} />);
    expect(screen.getByText("C")).toBeInTheDocument();
  });

  it("renders dash for unknown type", () => {
    // WHY: when the backend returns an unrecognised string the chip must fall back
    // to an em-dash rather than showing a confusing abbreviation.
    render(<AssetTypeCellRenderer {...buildParams("unknown_type")} />);
    expect(screen.getByText("—")).toBeInTheDocument();
  });

  it("renders dash when assetClass is null", () => {
    // WHY: null arrives when the context map has an explicit null entry (backend
    // returned null from the enrichment query). Must render "—" not crash.
    render(<AssetTypeCellRenderer {...buildParams(null)} />);
    expect(screen.getByText("—")).toBeInTheDocument();
  });

  it("renders dash when assetClass is missing from context", () => {
    // WHY: the context map may not yet have an entry for a newly-loaded instrument
    // (overviews load asynchronously after the row data). Must render "—".
    render(<AssetTypeCellRenderer {...buildParams(undefined)} />);
    expect(screen.getByText("—")).toBeInTheDocument();
  });

  it("renders dash for pinned bottom row (TOTAL footer)", () => {
    // WHY: the pinned TOTAL footer row aggregates across all instruments;
    // showing a chip would be misleading. The renderer must return "—".
    render(<AssetTypeCellRenderer {...buildParams("equity", "bottom")} />);
    expect(screen.getByText("—")).toBeInTheDocument();
  });
});
