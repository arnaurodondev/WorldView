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
  volumeBrightnessClass,
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

describe("Range52wCellRenderer — REAL 52W low/high tooltip (Wave-2)", () => {
  // Wave-2 (2026-06-10): the backend now ships ABSOLUTE high_52w / low_52w on
  // every row. The tooltip must prefer them over the old current_price-based
  // derivation — real values are exact and available for ~100% of rows, while
  // the derivation needed a live quote (~7% coverage).
  it("uses the real high_52w / low_52w values when present", () => {
    const { container } = renderCell("range52w", {
      dist_from_52w_low_pct: 0.3,
      dist_from_52w_high_pct: -0.1,
      // Real backend values — deliberately DIFFERENT from what the derivation
      // would produce (price 100 → derived low $76.92 / high $111.11) so this
      // test fails if the renderer falls back to deriving.
      low_52w: 80.5,
      high_52w: 120.25,
      current_price: 100,
    } as Partial<ScreenerResult>);
    const bar = container.querySelector("[title]") as HTMLElement;
    expect(bar.title).toContain("$80.50");
    expect(bar.title).toContain("$120.25");
    // The derived figures must NOT appear — real values take priority.
    expect(bar.title).not.toContain("$76.92");
    expect(bar.title).not.toContain("$111.11");
    // The relative position is still in the tooltip for context.
    expect(bar.title).toContain("75% of range");
  });

  it("falls back to deriving from current_price + distances when real values are absent", () => {
    // price = 100, dist_low = +0.30 → low = 100 / 1.30 = $76.92
    //              dist_high = −0.10 → high = 100 / 0.90 = $111.11
    // WHY keep this path: older cached payloads / backend rollback would
    // otherwise lose the dollar range entirely.
    const { container } = renderCell("range52w", {
      current_price: 100,
      dist_from_52w_low_pct: 0.3,
      dist_from_52w_high_pct: -0.1,
    });
    const bar = container.querySelector("[title]") as HTMLElement;
    expect(bar.title).toContain("$76.92");
    expect(bar.title).toContain("$111.11");
    expect(bar.title).toContain("75% of range");
  });

  it("omits the exact-price section when neither real values nor a price exist", () => {
    const { container } = renderCell("range52w", {
      current_price: null,
      dist_from_52w_low_pct: 0.3,
      dist_from_52w_high_pct: -0.1,
    });
    const bar = container.querySelector("[title]") as HTMLElement;
    // Still has the relative-position part…
    expect(bar.title).toContain("75% of range");
    // …but no dollar range (no real values, and we cannot derive without price).
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
// Wave-2 (2026-06-10): the column displays the LATEST 1-day `volume` (new flat
// backend field), no longer avg_volume_30d. The compact-notation contract is
// unchanged — same assertions, new source field.

describe("VolumeCellRenderer — compact notation on latest volume (Wave-2)", () => {
  it("formats 1,234,000 as 1.2M", () => {
    renderCell("volume", { volume: 1_234_000 } as Partial<ScreenerResult>);
    expect(screen.getByText("1.2M")).toBeInTheDocument();
  });

  it("formats 340,000 as 340K (adaptive: 0 decimals at ≥100 scaled)", () => {
    renderCell("volume", { volume: 340_000 } as Partial<ScreenerResult>);
    expect(screen.getByText("340K")).toBeInTheDocument();
  });

  it('renders "—" for null (no latest volume in the payload)', () => {
    renderCell("volume", { volume: null } as Partial<ScreenerResult>);
    expect(screen.getByText("—")).toBeInTheDocument();
  });

  it("ignores avg_volume_30d as a display source (only drives brightness)", () => {
    // A row with ONLY the 30d average must still dash — the cell shows
    // today's tape, never the average (that's the opt-in avgVol column's job).
    renderCell("volume", {
      volume: null,
      avg_volume_30d: 5_000_000,
    } as Partial<ScreenerResult>);
    expect(screen.getByText("—")).toBeInTheDocument();
    expect(screen.queryByText("5.0M")).not.toBeInTheDocument();
  });
});

describe("VolumeCellRenderer — brightness vs 30d average (Wave-2)", () => {
  // The brightness rule is the column's second data channel: full opacity
  // (text-foreground) = at/above average activity, dim (text-muted-foreground)
  // = below average. volumeBrightnessClass is the single source of truth.

  it("renders FULL brightness when volume ≥ 30d average", () => {
    renderCell("volume", {
      volume: 2_000_000,
      avg_volume_30d: 1_000_000, // ratio 2.0 → above average
    } as Partial<ScreenerResult>);
    const cell = screen.getByText("2.0M");
    expect(cell.className).toContain("text-foreground");
    expect(cell.className).not.toContain("text-muted-foreground");
  });

  it("renders DIM when volume < 30d average", () => {
    renderCell("volume", {
      volume: 500_000,
      avg_volume_30d: 1_000_000, // ratio 0.5 → below average
    } as Partial<ScreenerResult>);
    const cell = screen.getByText("500K");
    expect(cell.className).toContain("text-muted-foreground");
  });

  it("renders neutral full brightness when no 30d average exists (cannot judge)", () => {
    renderCell("volume", {
      volume: 500_000,
      avg_volume_30d: null,
    } as Partial<ScreenerResult>);
    const cell = screen.getByText("500K");
    // No ratio → neutral foreground, NOT dim (dim must always mean "below
    // average", never "unknown").
    expect(cell.className).toContain("text-foreground");
    expect(cell.className).not.toContain("text-muted-foreground");
  });

  it("exposes the exact ratio in the hover tooltip", () => {
    renderCell("volume", {
      volume: 1_400_000,
      avg_volume_30d: 1_000_000,
    } as Partial<ScreenerResult>);
    const cell = screen.getByText("1.4M");
    expect(cell.title).toContain("1.40× 30d avg");
  });
});

describe("volumeBrightnessClass — threshold contract (Wave-2)", () => {
  it("ratio exactly 1.0 counts as above-average (full brightness)", () => {
    expect(volumeBrightnessClass(1_000_000, 1_000_000)).toBe("text-foreground");
  });

  it("ratio just below 1.0 dims", () => {
    expect(volumeBrightnessClass(999_999, 1_000_000)).toBe("text-muted-foreground");
  });

  it("zero/negative average is treated as no-ratio (neutral, no divide-by-zero)", () => {
    expect(volumeBrightnessClass(1_000_000, 0)).toBe("text-foreground");
    expect(volumeBrightnessClass(1_000_000, null)).toBe("text-foreground");
  });

  it("null volume returns the muted dash tint", () => {
    expect(volumeBrightnessClass(null, 1_000_000)).toBe("text-muted-foreground");
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
