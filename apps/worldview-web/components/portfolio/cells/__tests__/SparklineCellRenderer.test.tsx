/**
 * components/portfolio/cells/__tests__/SparklineCellRenderer.test.tsx
 *
 * WHY THIS EXISTS: Regression guard for PLAN-0108 W4-T402 (SparklineCellRenderer
 * inline SVG). The tests lock in:
 *   - SVG rendering when a valid series is available.
 *   - Em-dash fallback when the series is empty or absent.
 *   - Trend colour logic: var(--color-positive) for uptrends, var(--color-negative)
 *     for downtrends.
 *
 * WHY params are built by hand (not via AgGridReact): the renderer is a plain
 * function — it receives an ICellRendererParams-shaped object and returns JSX.
 * We construct a minimal params stub so AG Grid itself is never instantiated,
 * keeping the test fast and free of DOM environment issues.
 *
 * WHY ticker-based lookup (not instrument_id): SemanticHoldingsTable passes
 * holdingsSeries keyed by ticker symbol (see inline comment in SemanticHoldingsTable
 * ~line 81). The renderer reads params.data.h.ticker and indexes the context map
 * with that string. Tests must mirror this key convention.
 */

import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import type { ICellRendererParams } from "ag-grid-community";
import { SparklineCellRenderer } from "@/components/portfolio/cells/SparklineCellRenderer";
import type { EnrichedHoldingRow } from "@/components/portfolio/holdings-columns";

// ── Helpers ────────────────────────────────────────────────────────────────────

const TICKER = "AAPL";

/**
 * buildParams — constructs a minimal ICellRendererParams stub for
 * SparklineCellRenderer.
 *
 * WHY partial cast with `as unknown as ICellRendererParams`: ICellRendererParams
 * has dozens of AG Grid internal fields (eGridCell, api, columnApi, …) that the
 * renderer never touches. Casting a partial object avoids hundreds of lines of
 * boilerplate while still satisfying TypeScript for the fields the renderer reads.
 *
 * @param series  The number[] to store in context.holdingsSeries[TICKER].
 *                Pass undefined to omit the context entry (simulates missing data).
 * @param pinned  When "bottom" the renderer should return null (footer row guard).
 */
function buildParams(
  series: number[] | undefined,
  pinned?: "bottom",
): ICellRendererParams<EnrichedHoldingRow> {
  return {
    // data: EnrichedHoldingRow — renderer reads data.h.ticker for the context lookup.
    data: {
      h: { ticker: TICKER } as EnrichedHoldingRow["h"],
    } as EnrichedHoldingRow,

    // node: IRowNode — renderer reads node.rowPinned for the footer guard.
    node: {
      rowPinned: pinned ?? null,
    },

    // context: SparklineCellContext injected by SemanticHoldingsTable.
    // When series is undefined we omit the key so the lookup returns undefined,
    // which mirrors "instrument not yet loaded" state.
    context:
      series !== undefined
        ? { holdingsSeries: { [TICKER]: series } }
        : { holdingsSeries: {} },
  } as unknown as ICellRendererParams<EnrichedHoldingRow>;
}

// ── Tests ──────────────────────────────────────────────────────────────────────

describe("SparklineCellRenderer", () => {
  it("renders SVG from array of 3 prices", () => {
    // WHY: core happy-path — a valid series with length >= 2 must render an
    // <svg> element. The test verifies the SVG is in the DOM; the exact path
    // geometry is covered by unit tests of buildSparkPath (not exported, so
    // we rely on the integration rendering here).
    render(<SparklineCellRenderer {...buildParams([10, 11, 12])} />);

    // querySelectorAll because getByRole("img") would also match the aria-label.
    const svg = document.querySelector("svg");
    expect(svg).not.toBeNull();
    expect(svg).toBeInTheDocument();
  });

  it("renders dash on empty array", () => {
    // WHY: an empty series (length 0) must produce the "—" placeholder, not
    // crash or render a broken SVG. This tests the `data.length < 2` guard.
    render(<SparklineCellRenderer {...buildParams([])} />);

    expect(screen.getByText("—")).toBeInTheDocument();
    expect(document.querySelector("svg")).toBeNull();
  });

  it("renders dash on single-element array", () => {
    // WHY: a single price point cannot form a meaningful line (we need at least
    // two points for M x0,y0 L x1,y1). The renderer must fall through to "—".
    render(<SparklineCellRenderer {...buildParams([42])} />);

    expect(screen.getByText("—")).toBeInTheDocument();
    expect(document.querySelector("svg")).toBeNull();
  });

  it("renders dash on undefined context entry", () => {
    // WHY: context.holdingsSeries may not yet have an entry for this ticker
    // (series loads asynchronously). The nullish-coalesce fallback to [] must
    // trigger the "—" placeholder without crashing.
    render(<SparklineCellRenderer {...buildParams(undefined)} />);

    expect(screen.getByText("—")).toBeInTheDocument();
    expect(document.querySelector("svg")).toBeNull();
  });

  it("uses positive color for uptrend (last > first)", () => {
    // WHY: a rising series [10, 11, 12] means last (12) > first (10), so the
    // stroke must use var(--color-positive) to signal a bullish trend. The test
    // reads the SVG <path> stroke attribute directly from the DOM.
    render(<SparklineCellRenderer {...buildParams([10, 11, 12])} />);

    const path = document.querySelector("svg path");
    expect(path).not.toBeNull();
    // WHY getAttribute("stroke") (not computed style): the renderer sets the
    // attribute directly with a CSS var() string. getComputedStyle would resolve
    // to an empty string in jsdom (no real CSS runtime). The attribute assertion
    // is the correct approach here.
    expect(path?.getAttribute("stroke")).toBe("var(--color-positive)");
  });

  it("uses negative color for downtrend (last < first)", () => {
    // WHY: a falling series [12, 11, 10] means last (10) < first (12), so the
    // stroke must use var(--color-negative) to signal a bearish trend.
    render(<SparklineCellRenderer {...buildParams([12, 11, 10])} />);

    const path = document.querySelector("svg path");
    expect(path).not.toBeNull();
    expect(path?.getAttribute("stroke")).toBe("var(--color-negative)");
  });

  it("uses negative color for flat trend (last === first)", () => {
    // WHY: a flat series [10, 10, 10] means last === first. The condition is
    // `last > first` (strictly greater), so flat maps to the negative (red)
    // colour. This is intentional: "no gain" is not a bullish signal.
    render(<SparklineCellRenderer {...buildParams([10, 10, 10])} />);

    const path = document.querySelector("svg path");
    expect(path).not.toBeNull();
    expect(path?.getAttribute("stroke")).toBe("var(--color-negative)");
  });

  it("returns null for pinned bottom row (TOTAL footer)", () => {
    // WHY: the pinned footer row aggregates across all instruments; showing a
    // sparkline would be meaningless (incompatible price scales). The renderer
    // must return null so AG Grid renders the cell as empty.
    // We wrap in a div because render(null) is valid React but screen queries
    // on an empty document would fail; checking childElementCount is cleaner.
    const { container } = render(
      <div data-testid="wrapper">
        <SparklineCellRenderer {...buildParams([10, 11, 12], "bottom")} />
      </div>,
    );

    // WHY childElementCount === 0: returning null from a React component leaves
    // the wrapper div empty. We confirm no SVG or span was rendered.
    const wrapper = container.firstChild as HTMLElement;
    expect(wrapper.childElementCount).toBe(0);
  });

  it("renders SVG with correct viewBox and dimensions", () => {
    // WHY: the viewBox must be "0 0 60 16" and width/height must match the
    // constants. These values are part of the public contract with the AG Grid
    // column width (60px) and row height (20px). A drift here would silently
    // clip the sparkline.
    render(<SparklineCellRenderer {...buildParams([5, 10, 8, 12])} />);

    const svg = document.querySelector("svg");
    expect(svg?.getAttribute("width")).toBe("60");
    expect(svg?.getAttribute("height")).toBe("16");
    expect(svg?.getAttribute("viewBox")).toBe("0 0 60 16");
    expect(svg?.getAttribute("preserveAspectRatio")).toBe("none");
  });
});
