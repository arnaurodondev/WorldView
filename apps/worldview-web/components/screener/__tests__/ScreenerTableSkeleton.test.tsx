/**
 * components/screener/__tests__/ScreenerTableSkeleton.test.tsx
 * (Round-3 enhancement sprint, item 4 — shape-matched loading skeleton)
 *
 * WHY THIS EXISTS: the skeleton's whole value is SHAPE-MATCHING the real grid
 * (20px pitch, header band + N rows, column-shaped cells). These tests pin:
 *   1. presence + a11y contract (role="status" with a label),
 *   2. the 20px pitch class (h-5) on header AND data rows — a regression to
 *      a different height would visibly jump when the real grid swaps in,
 *   3. the row count contract (default 16, overridable),
 *   4. column-shaping: every row renders one cell per skeleton column.
 */

import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";

import { ScreenerTableSkeleton } from "@/components/screener/ScreenerTableSkeleton";

describe("ScreenerTableSkeleton", () => {
  it("renders an accessible loading status region", () => {
    render(<ScreenerTableSkeleton />);
    expect(
      screen.getByRole("status", { name: /loading screener results/i }),
    ).toBeInTheDocument();
    expect(screen.getByTestId("screener-table-skeleton")).toBeInTheDocument();
  });

  it("renders one header band plus 16 data-row bands by default", () => {
    render(<ScreenerTableSkeleton />);
    expect(screen.getByTestId("skeleton-header-row")).toBeInTheDocument();
    expect(screen.getAllByTestId("skeleton-data-row")).toHaveLength(16);
  });

  it("honours the rows override", () => {
    render(<ScreenerTableSkeleton rows={5} />);
    expect(screen.getAllByTestId("skeleton-data-row")).toHaveLength(5);
  });

  it("uses the 20px pitch (h-5) on the header and every data row", () => {
    // WHY pin the class: the screener grid runs rowHeight={20}/headerHeight={20}
    // (T-IA-14 guard). If the skeleton pitch drifts (e.g. someone "fixes" it to
    // the 22px token), the loading→loaded swap visibly reflows.
    render(<ScreenerTableSkeleton rows={3} />);
    expect(screen.getByTestId("skeleton-header-row").className).toContain("h-5");
    for (const row of screen.getAllByTestId("skeleton-data-row")) {
      expect(row.className).toContain("h-5");
    }
  });

  it("is column-shaped: every band renders the same per-column cell count", () => {
    render(<ScreenerTableSkeleton rows={2} />);
    const header = screen.getByTestId("skeleton-header-row");
    const headerCells = header.children.length;
    // 15 default-visible columns mirrored from SCREENER_AG_COL_WIDTHS.
    expect(headerCells).toBeGreaterThanOrEqual(10);
    for (const row of screen.getAllByTestId("skeleton-data-row")) {
      expect(row.children.length).toBe(headerCells);
    }
  });
});

// ── Round-4 item 4: DS §6.2 — skeletons are STATIC ───────────────────────────

describe("ScreenerTableSkeleton — §6.2 static-skeleton rule (Round 4)", () => {
  it("contains NO raw animate-pulse anywhere (banned by DS §6.2)", () => {
    // WHY scan the whole subtree (not just the wrapper): the rule bans the
    // class on every skeleton element; a per-bar regression would be just as
    // wrong as the old wrapper-level one.
    const { container } = render(<ScreenerTableSkeleton rows={3} />);
    expect(container.innerHTML).not.toContain("animate-pulse");
  });

  it("does not opt into animate-skeleton-pulse either (cold query is <2s)", () => {
    // The 2s-plus opt-in tier is documented as NOT applying to the screener
    // (sub-second fundamentals scan) — see the WHY block in the component.
    // If the query ever genuinely slows past 2s, flip this assertion together
    // with the class, citing the measurement.
    const { container } = render(<ScreenerTableSkeleton rows={3} />);
    expect(container.innerHTML).not.toContain("animate-skeleton-pulse");
  });
});
