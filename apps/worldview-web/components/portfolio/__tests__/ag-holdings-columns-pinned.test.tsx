/**
 * components/portfolio/__tests__/ag-holdings-columns-pinned.test.tsx
 *
 * WHY THIS EXISTS (R1 sprint): the pinned TOTAL row previously rendered "—"
 * for DAY Δ$, DAY Δ% and WEIGHT. SemanticHoldingsTable now feeds real totals
 * into the pinned row (book-level day change, day %, weight sum) and the
 * renderers display them. These tests pin that behaviour at the renderer
 * level so a future "restore the em-dash" refactor cannot silently regress
 * the totals line.
 *
 * WHY render the cellRenderer functions directly (not a mounted AG Grid):
 * AG Grid needs ResizeObserver + real layout — unavailable in jsdom. The
 * renderers are plain function components reachable via
 * holdingsAgColumns[].cellRenderer, so we drive them with hand-built
 * ICellRendererParams stubs exactly like SparklineCellRenderer.test.tsx does.
 */

import { describe, it, expect, vi } from "vitest";
import { render, fireEvent } from "@testing-library/react";
import { createElement, type ComponentType } from "react";
import type { ICellRendererParams } from "ag-grid-community";
import { holdingsAgColumns } from "../ag-holdings-columns";
import type { EnrichedHoldingRow } from "../holdings-columns";

// ── Helpers ───────────────────────────────────────────────────────────────────

/**
 * rendererFor — pulls the cellRenderer component off a column definition.
 * Throws loudly if the column or renderer is missing so a column rename
 * fails the suite with a readable message instead of a cryptic null render.
 */
function rendererFor(colId: string): ComponentType<ICellRendererParams<EnrichedHoldingRow>> {
  const col = holdingsAgColumns.find((c) => c.colId === colId);
  if (!col?.cellRenderer) throw new Error(`No cellRenderer for colId="${colId}"`);
  return col.cellRenderer as ComponentType<ICellRendererParams<EnrichedHoldingRow>>;
}

/**
 * buildPinnedParams — minimal params stub for a pinned-bottom (TOTAL) row.
 * Mirrors the synthetic pinnedBottomRow object SemanticHoldingsTable builds:
 * a zero-value placeholder Holding plus the aggregate fields under test.
 */
function buildPinnedParams(
  rowOverrides: Partial<EnrichedHoldingRow> = {},
): ICellRendererParams<EnrichedHoldingRow> {
  const row: EnrichedHoldingRow = {
    h: {
      holding_id: "__totals__",
      portfolio_id: "",
      instrument_id: "",
      entity_id: "",
      ticker: "",
      name: "",
      quantity: 0,
      average_cost: 0,
    } as EnrichedHoldingRow["h"],
    livePrice: 0,
    freshness: undefined,
    value: 10_000,
    pnl: 0,
    pnlPct: 0,
    weight: 0,
    sector: null,
    dayChange: null,
    dayChangePct: null,
    dayChangeValue: null,
    annualizedDividendYield: null,
    ...rowOverrides,
  };
  return {
    data: row,
    node: { rowPinned: "bottom" },
  } as unknown as ICellRendererParams<EnrichedHoldingRow>;
}

// ── DAY Δ$ totals ─────────────────────────────────────────────────────────────

describe("DAY Δ$ pinned TOTAL cell (R1 sprint)", () => {
  it("renders the signed book-level day change with positive colour", () => {
    const DayChange = rendererFor("dayChange");
    const { container } = render(
      createElement(DayChange, buildPinnedParams({ dayChangeValue: 123.45 })),
    );
    const span = container.querySelector("span");
    // fmtPnl prefixes "+" on gains — the totals line must read direction
    // without relying on colour alone.
    expect(span?.textContent).toBe("+$123.45");
    expect(span?.className).toContain("text-positive");
    // Totals line renders heavier than data rows (matches UNREAL $ total).
    expect(span?.className).toContain("font-semibold");
  });

  it("renders a negative day change with negative colour", () => {
    const DayChange = rendererFor("dayChange");
    const { container } = render(
      createElement(DayChange, buildPinnedParams({ dayChangeValue: -42 })),
    );
    const span = container.querySelector("span");
    expect(span?.textContent).toBe("-$42.00");
    expect(span?.className).toContain("text-negative");
  });

  it("renders an em-dash when no quotes have arrived (dayChangeValue null)", () => {
    // WHY: null means "unknown", not $0 — the totals row must not fabricate
    // a flat day while the batch-quote query is still in flight.
    const DayChange = rendererFor("dayChange");
    const { container } = render(createElement(DayChange, buildPinnedParams()));
    expect(container.textContent).toBe("—");
  });
});

// ── DAY Δ% totals ─────────────────────────────────────────────────────────────

describe("DAY Δ% pinned TOTAL cell (R1 sprint)", () => {
  it("renders the signed portfolio-level day percentage", () => {
    const DayChangePct = rendererFor("dayChangePct");
    const { container } = render(
      createElement(DayChangePct, buildPinnedParams({ dayChangePct: 1.25 })),
    );
    const span = container.querySelector("span");
    // dayChangePct is stored as a percentage value (1.25 = +1.25%); the
    // renderer divides by 100 before formatPercent re-scales it.
    expect(span?.textContent).toBe("+1.25%");
    expect(span?.className).toContain("text-positive");
    expect(span?.className).toContain("font-semibold");
  });

  it("renders an em-dash when the percentage is unknown", () => {
    const DayChangePct = rendererFor("dayChangePct");
    const { container } = render(createElement(DayChangePct, buildPinnedParams()));
    expect(container.textContent).toBe("—");
  });
});

// ── SECTOR cell (DESIGN-QA P-2) ───────────────────────────────────────────────

describe("SECTOR cell (DESIGN-QA P-2 — column must not render '—' when a sector is present)", () => {
  // The audit found the SECTOR column showing "—" for EVERY holding even
  // though the SECTOR EXPOSURE panel knew each sector. The data-wiring fix
  // (SemanticHoldingsTable now falls back to the /sector-breakdown source) is
  // exercised via the component; here we pin the RENDERER contract so it never
  // regresses to a hardcoded dash: given a row with a sector, it must show it.
  function buildDataParams(
    rowOverrides: Partial<EnrichedHoldingRow> = {},
  ): ICellRendererParams<EnrichedHoldingRow> {
    const row: EnrichedHoldingRow = {
      h: {
        holding_id: "h-1",
        portfolio_id: "p-1",
        instrument_id: "iid-1",
        entity_id: "e-1",
        ticker: "MSFT",
        name: "Microsoft Corporation",
        quantity: 30,
        average_cost: 412.75,
      } as EnrichedHoldingRow["h"],
      livePrice: 400,
      freshness: undefined,
      value: 12_000,
      pnl: 0,
      pnlPct: 0,
      weight: 50,
      sector: "Technology",
      dayChange: null,
      dayChangePct: null,
      dayChangeValue: null,
      annualizedDividendYield: null,
      ...rowOverrides,
    };
    return {
      data: row,
      node: { rowPinned: null },
    } as unknown as ICellRendererParams<EnrichedHoldingRow>;
  }

  it("renders the resolved sector name", () => {
    const Sector = rendererFor("sector");
    const { container } = render(createElement(Sector, buildDataParams()));
    expect(container.textContent).toBe("Technology");
    // Full label rides the tooltip (truncation convention).
    expect(container.querySelector("span")?.getAttribute("title")).toBe(
      "Technology",
    );
  });

  it("falls back to '—' only when the row genuinely has no sector", () => {
    const Sector = rendererFor("sector");
    const { container } = render(
      createElement(Sector, buildDataParams({ sector: null })),
    );
    expect(container.textContent).toBe("—");
  });
});

// ── ACTIONS kebab cell (PLAN-0122 W-D §6.6) ───────────────────────────────────

describe("ACTIONS pinned-right kebab cell (PLAN-0122 W-D)", () => {
  it("test_actions_empty_on_total_row: the pinned TOTAL row renders an empty ACTIONS cell", () => {
    // WHY: the totals footer has no per-row actions — the kebab must not render
    // on it (R-22). ActionsCellRenderer returns null for a pinned-bottom row.
    const Actions = rendererFor("actions");
    const { container } = render(createElement(Actions, buildPinnedParams()));
    expect(container.textContent).toBe("");
    expect(container.querySelector("button")).toBeNull();
  });

  it("renders a kebab button with an aria-label naming the row on a data row", () => {
    const Actions = rendererFor("actions");
    const params = {
      data: {
        h: {
          holding_id: "h-1",
          portfolio_id: "p-1",
          instrument_id: "iid-1",
          entity_id: "e-1",
          ticker: "AAPL",
          name: "Apple Inc.",
          quantity: 10,
          average_cost: 100,
        },
        livePrice: 150,
        value: 1500,
        pnl: 500,
        pnlPct: 50,
        weight: 100,
        sector: null,
        dayChange: null,
        dayChangePct: null,
        dayChangeValue: null,
        annualizedDividendYield: null,
      },
      node: { rowPinned: null },
    } as unknown as ICellRendererParams<EnrichedHoldingRow>;
    const { getByRole } = render(createElement(Actions, params));
    // aria-label pins the ticker so screen-reader users know the target.
    expect(getByRole("button", { name: /actions for aapl/i })).toBeInTheDocument();
  });

  it("clicking the kebab calls context.onOpenRowMenu with the row", () => {
    // WHY assert the callback (not the menu): the ACTIONS cell's ONLY job is to
    // REQUEST the menu open via context.onOpenRowMenu — the menu itself lives in
    // SemanticHoldingsTable. This pins the reuse contract (no duplicate menu).
    const onOpenRowMenu = vi.fn();
    const Actions = rendererFor("actions");
    const rowData = {
      h: {
        holding_id: "h-2",
        portfolio_id: "p-1",
        instrument_id: "iid-2",
        entity_id: "e-2",
        ticker: "MSFT",
        name: "Microsoft",
        quantity: 5,
        average_cost: 400,
      },
      livePrice: 420,
      value: 2100,
      pnl: 100,
      pnlPct: 5,
      weight: 100,
      sector: null,
      dayChange: null,
      dayChangePct: null,
      dayChangeValue: null,
      annualizedDividendYield: null,
    };
    const params = {
      data: rowData,
      node: { rowPinned: null },
      context: { onOpenRowMenu },
    } as unknown as ICellRendererParams<EnrichedHoldingRow>;
    const { getByRole } = render(createElement(Actions, params));
    fireEvent.click(getByRole("button", { name: /actions for msft/i }));
    expect(onOpenRowMenu).toHaveBeenCalledOnce();
    // First arg is the enriched row (so the menu can build the row context).
    expect(onOpenRowMenu.mock.calls[0][0]).toBe(rowData);
  });
});

// ── WEIGHT totals ─────────────────────────────────────────────────────────────

describe("WEIGHT pinned TOTAL cell (R1 sprint)", () => {
  it("renders the weight-column sum (sanity-check that weights ≈ 100%)", () => {
    const Weight = rendererFor("weight");
    const { container } = render(
      createElement(Weight, buildPinnedParams({ weight: 100 })),
    );
    const span = container.querySelector("span");
    expect(span?.textContent).toBe("100.00%");
    expect(span?.className).toContain("font-semibold");
    // No leading "+": weight is an allocation, not a directional gain.
    expect(span?.textContent).not.toContain("+");
  });

  it("renders an em-dash for an empty book (weight 0)", () => {
    // WHY: a zero total weight means no priced positions — showing "0.00%"
    // would imply the column was computed when it genuinely has no data.
    const Weight = rendererFor("weight");
    const { container } = render(
      createElement(Weight, buildPinnedParams({ weight: 0 })),
    );
    expect(container.textContent).toBe("—");
  });
});
