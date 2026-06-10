/**
 * components/screener/__tests__/range52w-volume-alignment.test.tsx
 * ROUND-1 Foundation sprint (2026-06-10) — screener surface.
 *
 * WHY THIS FILE EXISTS:
 *   Round 1 items 2–5 changed three load-bearing behaviours that previously
 *   had no direct test coverage:
 *     1. 52W RANGE renderer — explicit "—" for missing data (was an empty
 *        grey bar that looked like "price at 52W low"), red→amber→green
 *        position colouring, and a tooltip carrying the DERIVED exact 52W
 *        low/high prices (low = price / (1 + dist_low), etc.).
 *     2. VOLUME renderer — compact notation (1.2M / 340K) with "—" for null.
 *     3. Numeric column alignment — every numeric leaf ColDef must carry AG
 *        Grid's built-in `rightAligned` type (finance convention: decimal
 *        axes align so magnitudes compare vertically).
 *     4. Sortability — every numeric column must be sortable, including the
 *        two derived columns (ANALYST UPSIDE, 52W RANGE) which sort via
 *        valueGetter because they have no single backend field.
 *
 * HOW RENDERERS ARE TESTED:
 *   AG Grid cell renderers are plain React components — we extract them from
 *   the ColDef list returned by createAgScreenerColumns and render them
 *   directly with a minimal ICellRendererParams-shaped prop object. This
 *   avoids mounting the full grid (slow, needs layout) while still testing
 *   the exact component AG Grid will call.
 */

import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import type { ColDef, ColGroupDef, ICellRendererParams, ValueGetterParams } from "ag-grid-community";
import type { ScreenerResult } from "@/types/api";
import {
  createAgScreenerColumns,
  NUMERIC_COL_IDS,
} from "@/components/screener/ag-screener-columns";

// ── Helpers ───────────────────────────────────────────────────────────────────

type ScreenerColDef = ColDef<ScreenerResult>;
type ScreenerColGroupDef = ColGroupDef<ScreenerResult>;

/** Flatten group defs into leaf ColDefs (the screener has depth-1 groups only). */
function leafColumns(): ScreenerColDef[] {
  const defs = createAgScreenerColumns({});
  const leaves: ScreenerColDef[] = [];
  for (const def of defs) {
    if ("children" in def) {
      leaves.push(...((def as ScreenerColGroupDef).children as ScreenerColDef[]));
    } else {
      leaves.push(def as ScreenerColDef);
    }
  }
  return leaves;
}

function colById(colId: string): ScreenerColDef {
  const col = leafColumns().find((c) => c.colId === colId);
  if (!col) throw new Error(`ColDef ${colId} not found`);
  return col;
}

/**
 * renderCell — render a ColDef's cellRenderer with a partial ScreenerResult.
 * WHY the double-cast: ICellRendererParams has ~30 grid-internal fields the
 * renderers never read; constructing them all would only add noise.
 */
function renderCell(colId: string, data: Partial<ScreenerResult>) {
  const col = colById(colId);
  const Renderer = col.cellRenderer as React.FC<ICellRendererParams<ScreenerResult>>;
  return render(
    <Renderer {...({ data } as unknown as ICellRendererParams<ScreenerResult>)} />,
  );
}

/** Run a ColDef's valueGetter with a partial row. */
function runValueGetter(colId: string, data: Partial<ScreenerResult>): unknown {
  const col = colById(colId);
  const getter = col.valueGetter as (p: ValueGetterParams<ScreenerResult>) => unknown;
  expect(typeof getter).toBe("function");
  return getter({ data } as unknown as ValueGetterParams<ScreenerResult>);
}

// ── 52W RANGE renderer ────────────────────────────────────────────────────────

describe("Range52wCellRenderer — explicit missing-data dash (ROUND-1 item 1/2)", () => {
  it('renders "—" (not an empty bar) when both distances are null', () => {
    renderCell("range52w", {
      dist_from_52w_low_pct: null,
      dist_from_52w_high_pct: null,
    });
    expect(screen.getByText("—")).toBeInTheDocument();
    expect(screen.getByTitle("No 52W range data")).toBeInTheDocument();
  });

  it('renders "—" when only one distance is present (cannot derive position)', () => {
    renderCell("range52w", {
      dist_from_52w_low_pct: 0.3,
      dist_from_52w_high_pct: null,
    });
    expect(screen.getByText("—")).toBeInTheDocument();
  });
});

describe("Range52wCellRenderer — proportional bar + colour shift", () => {
  it("fills 75% and uses bg-positive when price is near the 52W high", () => {
    // dist_low = +30% above low, dist_high = −10% below high
    // fill = 0.3 / (0.3 + 0.1) = 75% → ≥70% → positive (green)
    const { container } = renderCell("range52w", {
      dist_from_52w_low_pct: 0.3,
      dist_from_52w_high_pct: -0.1,
    });
    const fill = container.querySelector(".bg-positive\\/70") as HTMLElement;
    expect(fill).not.toBeNull();
    // WHY parseFloat + toBeCloseTo (not string equality): 0.3 / (0.3 + 0.1)
    // is 0.7499999999999999 in IEEE-754 — the style attribute carries the
    // full float. The browser renders it identically to 75%.
    expect(parseFloat(fill.style.width)).toBeCloseTo(75);
  });

  it("uses bg-negative when price is near the 52W low (≤30% of range)", () => {
    // fill = 0.02 / (0.02 + 0.5) ≈ 3.8% → ≤30% → negative (red)
    const { container } = renderCell("range52w", {
      dist_from_52w_low_pct: 0.02,
      dist_from_52w_high_pct: -0.5,
    });
    expect(container.querySelector(".bg-negative\\/70")).not.toBeNull();
  });

  it("uses bg-warning for the mid-range (between 30% and 70%)", () => {
    // fill = 0.3 / (0.3 + 0.3) = 50% → warning (amber)
    const { container } = renderCell("range52w", {
      dist_from_52w_low_pct: 0.3,
      dist_from_52w_high_pct: -0.3,
    });
    expect(container.querySelector(".bg-warning\\/70")).not.toBeNull();
  });

  it("shows 100% fill when price is exactly at the 52W high (both distances 0)", () => {
    const { container } = renderCell("range52w", {
      dist_from_52w_low_pct: 0,
      dist_from_52w_high_pct: 0,
    });
    const fill = container.querySelector(".bg-positive\\/70") as HTMLElement;
    expect(fill).not.toBeNull();
    expect(fill.style.width).toBe("100%");
  });
});

describe("Range52wCellRenderer — derived exact low/high tooltip (ROUND-1 item 2)", () => {
  it("derives exact 52W low and high prices from current_price + distances", () => {
    // price = 100, dist_low = +0.30 → low = 100 / 1.30 = $76.92
    //              dist_high = −0.10 → high = 100 / 0.90 = $111.11
    const { container } = renderCell("range52w", {
      current_price: 100,
      dist_from_52w_low_pct: 0.3,
      dist_from_52w_high_pct: -0.1,
    });
    const bar = container.querySelector("[title]") as HTMLElement;
    expect(bar.title).toContain("$76.92");
    expect(bar.title).toContain("$111.11");
    // The relative position is still in the tooltip for context.
    expect(bar.title).toContain("75% of range");
  });

  it("omits the exact-price section when current_price is missing", () => {
    const { container } = renderCell("range52w", {
      current_price: null,
      dist_from_52w_low_pct: 0.3,
      dist_from_52w_high_pct: -0.1,
    });
    const bar = container.querySelector("[title]") as HTMLElement;
    // Still has the relative-position part…
    expect(bar.title).toContain("75% of range");
    // …but no derived dollar range (we cannot derive low/high without price).
    expect(bar.title).not.toContain("52W low $");
  });
});

describe("range52w valueGetter — sortable derived position (ROUND-1 item 5)", () => {
  it("returns the position fraction (0=low … 1=high)", () => {
    expect(
      runValueGetter("range52w", {
        dist_from_52w_low_pct: 0.3,
        dist_from_52w_high_pct: -0.1,
      }),
    ).toBeCloseTo(0.75);
  });

  it("returns null when data is missing (sorts missing rows together)", () => {
    expect(
      runValueGetter("range52w", {
        dist_from_52w_low_pct: null,
        dist_from_52w_high_pct: -0.1,
      }),
    ).toBeNull();
  });

  it("returns 1 when price is exactly at the high (zero span)", () => {
    expect(
      runValueGetter("range52w", {
        dist_from_52w_low_pct: 0,
        dist_from_52w_high_pct: 0,
      }),
    ).toBe(1);
  });
});

// ── ANALYST UPSIDE valueGetter ────────────────────────────────────────────────

describe("analystUpside valueGetter — sortable derived upside (ROUND-1 item 5)", () => {
  it("computes (target / price) − 1", () => {
    expect(
      runValueGetter("analystUpside", {
        analyst_target_price: 120,
        current_price: 100,
      }),
    ).toBeCloseTo(0.2);
  });

  it("returns null when price is missing or zero (avoids divide-by-zero)", () => {
    expect(
      runValueGetter("analystUpside", { analyst_target_price: 120, current_price: null }),
    ).toBeNull();
    expect(
      runValueGetter("analystUpside", { analyst_target_price: 120, current_price: 0 }),
    ).toBeNull();
  });

  it("is sortable (was sortable: false before ROUND-1)", () => {
    expect(colById("analystUpside").sortable).toBe(true);
  });
});

// ── VOLUME renderer ───────────────────────────────────────────────────────────

describe("VolumeCellRenderer — compact notation (ROUND-1 item 3)", () => {
  it("formats 1,234,000 as 1.2M", () => {
    renderCell("volume", { avg_volume_30d: 1_234_000 });
    expect(screen.getByText("1.2M")).toBeInTheDocument();
  });

  it("formats 340,000 as 340K (adaptive: 0 decimals at ≥100 scaled)", () => {
    renderCell("volume", { avg_volume_30d: 340_000 });
    expect(screen.getByText("340K")).toBeInTheDocument();
  });

  it('renders "—" for null (no avg_volume_30d in the payload)', () => {
    renderCell("volume", { avg_volume_30d: null });
    expect(screen.getByText("—")).toBeInTheDocument();
  });
});

// ── Numeric alignment + sortability contract ─────────────────────────────────

describe("numeric column alignment (ROUND-1 item 4)", () => {
  it('every numeric column carries AG Grid\'s built-in "rightAligned" type', () => {
    const leaves = leafColumns();
    for (const id of NUMERIC_COL_IDS) {
      const col = leaves.find((c) => c.colId === id);
      expect(col, `missing ColDef for numeric colId ${id}`).toBeDefined();
      expect(col?.type, `colId ${id} must be rightAligned`).toBe("rightAligned");
    }
  });

  it("text and visual columns are NOT right-aligned", () => {
    for (const id of ["ticker", "name", "sector", "score", "range52w", "sparkline"]) {
      expect(colById(id).type, `colId ${id} must stay default-aligned`).toBeUndefined();
    }
  });

  it("every numeric column is sortable (ROUND-1 item 5)", () => {
    for (const id of NUMERIC_COL_IDS) {
      expect(colById(id).sortable, `colId ${id} must be sortable`).toBe(true);
    }
  });
});
