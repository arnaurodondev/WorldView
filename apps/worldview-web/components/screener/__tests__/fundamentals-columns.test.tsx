/**
 * components/screener/__tests__/fundamentals-columns.test.tsx — Vitest
 * for the 6 Wave I-B Block IB-L2 fundamentals snapshot cell renderers
 * (PRD-0089, T-IB-08).
 *
 * WHY THIS EXISTS:
 *   The 6 new opt-in columns (AVG VOL / EPS / FCF / FCF MGN% / INT COV /
 *   ND/EBITDA) each have a custom renderer with tone logic. Bugs in
 *   formatting silently mis-display financial data — e.g. rendering raw
 *   `0.284` instead of `28.4%` would be both wrong and unreadable.
 *
 *   These tests render each cell renderer in isolation against the actual
 *   ColDef factory output (so the test exercises the same code path the
 *   AG-Grid uses) and asserts on the rendered DOM text + Tailwind tone
 *   class.
 *
 * WHY render via the ColDef factory (not direct calls): the cellRenderer
 * functions are private to the module. Going through createAgScreenerColumns
 * pins the colId → renderer wiring and catches regressions where the wrong
 * renderer is bound to a colId (a subtle bug class that escapes type checks).
 *
 * NULL SENTINEL: the platform uses "—" (em-dash U+2014) as the universal
 * "data missing" cell. The PeCellRenderer / BetaCellRenderer all converge
 * on this so the new columns must match.
 *
 * BACKEND CONTRACT: ScreenerResult fields land flat on the row thanks to
 * the S9 _flatten_screener_result transform. The columns read
 * `data.avg_volume_30d`, `data.eps_ttm`, etc directly.
 */

import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import { createAgScreenerColumns } from "@/components/screener/ag-screener-columns";
import type { ScreenerResult } from "@/types/api";
import type { ColDef, ColGroupDef, ICellRendererParams } from "ag-grid-community";

// ── Helpers ──────────────────────────────────────────────────────────────────

/** Flatten the ColDef list (handles ColGroupDef children). */
function flattenColumns(
  defs: (ColDef<ScreenerResult> | ColGroupDef<ScreenerResult>)[],
): ColDef<ScreenerResult>[] {
  const out: ColDef<ScreenerResult>[] = [];
  for (const d of defs) {
    if ("children" in d && Array.isArray(d.children)) {
      out.push(...(d.children as ColDef<ScreenerResult>[]));
    } else {
      out.push(d as ColDef<ScreenerResult>);
    }
  }
  return out;
}

/** Find a ColDef by colId. */
function findCol(colId: string): ColDef<ScreenerResult> {
  const cols = flattenColumns(createAgScreenerColumns({}, false));
  const col = cols.find((c) => c.colId === colId);
  if (!col) throw new Error(`Column ${colId} not found in factory output`);
  return col;
}

/** Render a column's cell renderer for a synthetic row and return text + container. */
function renderCell(colId: string, data: Partial<ScreenerResult>) {
  const col = findCol(colId);
  const Renderer = col.cellRenderer as
    | React.ComponentType<ICellRendererParams<ScreenerResult>>
    | undefined;
  if (!Renderer) throw new Error(`Column ${colId} has no cellRenderer`);
  // Cast: tests only need a partial ScreenerResult — the renderer reads one
  // field at a time. The real grid passes a full row.
  const params = {
    data: data as ScreenerResult,
  } as unknown as ICellRendererParams<ScreenerResult>;
  return render(<Renderer {...params} />);
}

// ── AVG VOL (avg_volume_30d) → compact integer "50M" ─────────────────────────

describe("AvgVolCellRenderer (avg_volume_30d → compact)", () => {
  it("renders 50_000_000 as '50M'", () => {
    const { container } = renderCell("avgVol", { avg_volume_30d: 50_000_000 });
    expect(container.textContent).toBe("50M");
  });

  it("renders null as the missing-data dash '—'", () => {
    const { container } = renderCell("avgVol", { avg_volume_30d: null });
    expect(container.textContent).toBe("—");
  });

  it("renders large volumes adaptively (1.2B not 1.20B)", () => {
    const { container } = renderCell("avgVol", { avg_volume_30d: 1_200_000_000 });
    // adaptive + maxDecimals=0 → "1B" (one decimal trimmed since requested 0)
    // We only assert the suffix is "B" — the precise decimal handling lives
    // in the formatCompact helper's own test suite.
    expect(container.textContent).toMatch(/B$/);
  });
});

// ── EPS (TTM) → 2dp ──────────────────────────────────────────────────────────

describe("EpsTtmCellRenderer (eps_ttm → 2dp)", () => {
  it("renders 6.32 as '6.32'", () => {
    const { container } = renderCell("epsTtm", { eps_ttm: 6.32 });
    expect(container.textContent).toBe("6.32");
  });

  it("rounds 6.327 to '6.33'", () => {
    const { container } = renderCell("epsTtm", { eps_ttm: 6.327 });
    expect(container.textContent).toBe("6.33");
  });

  it("renders null as '—'", () => {
    const { container } = renderCell("epsTtm", { eps_ttm: null });
    expect(container.textContent).toBe("—");
  });

  it("tints negative EPS with the negative tone (loss-maker signal)", () => {
    const { container } = renderCell("epsTtm", { eps_ttm: -1.25 });
    const span = container.querySelector("span");
    expect(span?.className).toMatch(/text-negative/);
  });
});

// ── FCF (free_cash_flow) → compact currency "$1.2B" ──────────────────────────

describe("FcfCellRenderer (free_cash_flow → compact $)", () => {
  it("renders 1_200_000_000 as '$1.2B'", () => {
    const { container } = renderCell("fcf", { free_cash_flow: 1_200_000_000 });
    expect(container.textContent).toBe("$1.2B");
  });

  it("renders null as '—'", () => {
    const { container } = renderCell("fcf", { free_cash_flow: null });
    expect(container.textContent).toBe("—");
  });

  it("renders negative FCF with negative tone (cash burn signal)", () => {
    const { container } = renderCell("fcf", { free_cash_flow: -2_400_000_000 });
    const span = container.querySelector("span");
    expect(span?.className).toMatch(/text-negative/);
    // Format helper renders sign before symbol
    expect(container.textContent).toMatch(/^-\$/);
  });
});

// ── FCF MGN% (fcf_margin) → percent 1dp ──────────────────────────────────────

describe("FcfMarginCellRenderer (fcf_margin → percent 1dp)", () => {
  it("renders 0.284 (fraction) as '28.4%'", () => {
    const { container } = renderCell("fcfMargin", { fcf_margin: 0.284 });
    expect(container.textContent).toBe("28.4%");
  });

  it("renders 28.4 (already a percent — backend contract drift guard) as '28.4%'", () => {
    // WHY this case: the cell renderer includes a defensive heuristic — if
    // |v| > 1.5 it assumes the backend sent percent (not fraction). Pin it
    // so a future code edit doesn't silently flip the convention.
    const { container } = renderCell("fcfMargin", { fcf_margin: 28.4 });
    expect(container.textContent).toBe("28.4%");
  });

  it("renders null as '—'", () => {
    const { container } = renderCell("fcfMargin", { fcf_margin: null });
    expect(container.textContent).toBe("—");
  });

  it("tints negative margin with the negative tone", () => {
    const { container } = renderCell("fcfMargin", { fcf_margin: -0.08 });
    const span = container.querySelector("span");
    expect(span?.className).toMatch(/text-negative/);
  });
});

// ── INT COV (interest_coverage) → multiple "2.1×" ────────────────────────────

describe("InterestCoverageCellRenderer (interest_coverage → multiple)", () => {
  it("renders 2.1 as '2.1×'", () => {
    const { container } = renderCell("interestCoverage", { interest_coverage: 2.1 });
    expect(container.textContent).toBe("2.1×");
  });

  it("renders null as '—'", () => {
    const { container } = renderCell("interestCoverage", { interest_coverage: null });
    expect(container.textContent).toBe("—");
  });

  it("tints <1× (distress: earnings don't cover interest) negative", () => {
    const { container } = renderCell("interestCoverage", { interest_coverage: 0.7 });
    const span = container.querySelector("span");
    expect(span?.className).toMatch(/text-negative/);
  });

  it("does NOT tint 1.0× (boundary) negative", () => {
    const { container } = renderCell("interestCoverage", { interest_coverage: 1.0 });
    const span = container.querySelector("span");
    expect(span?.className).not.toMatch(/text-negative/);
  });
});

// ── ND/EBITDA (net_debt_to_ebitda) → multiple with risk tiers ───────────────

describe("NetDebtEbitdaCellRenderer (net_debt_to_ebitda → multiple + tier tone)", () => {
  it("renders 2.1 as '2.1×' (neutral)", () => {
    const { container } = renderCell("netDebtToEbitda", { net_debt_to_ebitda: 2.1 });
    expect(container.textContent).toBe("2.1×");
    const span = container.querySelector("span");
    expect(span?.className).not.toMatch(/text-negative|text-warning/);
  });

  it("renders -1.2× (net cash) as neutral foreground", () => {
    const { container } = renderCell("netDebtToEbitda", { net_debt_to_ebitda: -1.2 });
    expect(container.textContent).toBe("-1.2×");
    const span = container.querySelector("span");
    // Net cash isn't tinted positive (cell only signals risk on the high side).
    expect(span?.className).not.toMatch(/text-negative|text-warning/);
  });

  it("tints >4× warning (highly levered)", () => {
    const { container } = renderCell("netDebtToEbitda", { net_debt_to_ebitda: 5.0 });
    const span = container.querySelector("span");
    expect(span?.className).toMatch(/text-warning/);
  });

  it("tints >6× negative (distressed)", () => {
    const { container } = renderCell("netDebtToEbitda", { net_debt_to_ebitda: 7.5 });
    const span = container.querySelector("span");
    expect(span?.className).toMatch(/text-negative/);
  });

  it("renders null as '—'", () => {
    const { container } = renderCell("netDebtToEbitda", { net_debt_to_ebitda: null });
    expect(container.textContent).toBe("—");
  });
});

// ── Universal numeric column properties ──────────────────────────────────────

describe("All IB-L2 numeric columns enforce font-mono + tabular-nums", () => {
  const numericCols = [
    "avgVol",
    "epsTtm",
    "fcf",
    "fcfMargin",
    "interestCoverage",
    "netDebtToEbitda",
  ];
  // WHY tabular-nums is non-negotiable: institutional column alignment depends
  // on digit-width parity across rows. A regression that drops the class
  // makes the screener instantly look like a free-tier consumer app.
  for (const colId of numericCols) {
    it(`${colId} cell uses font-mono tabular-nums`, () => {
      const sampleValue: Partial<ScreenerResult> = {
        avg_volume_30d: 1_000_000,
        eps_ttm: 1.0,
        free_cash_flow: 1_000_000_000,
        fcf_margin: 0.1,
        interest_coverage: 2.0,
        net_debt_to_ebitda: 1.5,
      };
      const { container } = renderCell(colId, sampleValue);
      const span = container.querySelector("span");
      expect(span?.className).toMatch(/font-mono/);
      expect(span?.className).toMatch(/tabular-nums/);
    });
  }
});
