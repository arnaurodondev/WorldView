/**
 * __tests__/portfolio-wave-f-components.test.tsx — Wave F pure-component tests
 *
 * WHY THIS FILE: The task spec (PLAN-0089 Wave F) requires Vitest unit tests for
 * two pure presentational components:
 *   1. SparklineCellRenderer — renders a 60×16 SVG from a price series array
 *   2. SectorAllocationBar   — renders a stacked horizontal bar from sector data
 *
 * WHY UNIT TESTS (not integration): both components are pure presenters — no
 * hooks, no API calls, no router. A jsdom render + assertion is both fast and
 * sufficient to pin the observable DOM contracts:
 *   - SparklineCellRenderer: uses the Sparkline primitive with correct dimensions
 *   - SectorAllocationBar: stacked segments sum to ~100% of bar width
 *
 * SCOPE: this file does NOT test the AG Grid wiring or the data-fetching hooks.
 * Those are tested by the AG Grid integration suite (ag-holdings-columns.test.ts)
 * and by the hook tests respectively.
 */

import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";

// ── Mocks ────────────────────────────────────────────────────────────────────

// next/navigation is pulled in transitively by Link imports.
vi.mock("next/navigation", () => ({
  useRouter: vi.fn(() => ({
    push: vi.fn(),
    replace: vi.fn(),
    prefetch: vi.fn(),
  })),
  usePathname: vi.fn(() => "/portfolio"),
  useSearchParams: vi.fn(() => new URLSearchParams()),
}));

// ── SUT imports ───────────────────────────────────────────────────────────────
import { SparklineCellRenderer } from "@/components/portfolio/cells/SparklineCellRenderer";
import { SectorAllocationBar } from "@/components/portfolio/SectorAllocationBar";
import type { AllocationSlice } from "@/features/portfolio/lib/kpi";

// ─────────────────────────────────────────────────────────────────────────────
// SparklineCellRenderer tests
// ─────────────────────────────────────────────────────────────────────────────

describe("SparklineCellRenderer — 60×16 SVG from price array", () => {
  /**
   * Minimal AG Grid ICellRendererParams factory.
   *
   * WHY factory function (not a shared object): each test needs isolated params
   * so one test's mutation can't bleed into another. AG Grid params in tests are
   * partial — we only supply the fields SparklineCellRenderer actually reads.
   */
  function makeParams(options: {
    ticker?: string;
    series?: number[];
    isPinned?: boolean;
  }) {
    // WHY cast: ICellRendererParams is a large interface; partial is fine in
    // tests because the renderer only accesses specific fields (data.h.ticker,
    // node.rowPinned, context.holdingsSeries).
    return {
      data: options.ticker
        ? { h: { ticker: options.ticker, instrument_id: "ins-1" } }
        : undefined,
      node: options.isPinned ? { rowPinned: "bottom" as const } : { rowPinned: undefined },
      context: options.series
        ? { holdingsSeries: { [options.ticker ?? ""]: options.series } }
        : undefined,
      // Required by ICellRendererParams but unused by this renderer.
      value: null,
      getValue: () => null,
      setValue: () => {},
      refreshCell: () => {},
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    } as any;
  }

  it("renders an SVG element when a series with ≥2 points is provided", () => {
    const series = [100, 102, 101, 105, 103, 106, 108];
    const { container } = render(
      <SparklineCellRenderer {...makeParams({ ticker: "AAPL", series })} />,
    );
    // The Sparkline primitive renders an <svg> element.
    // WHY querySelector (not screen.getBy*): the SVG doesn't have a role or
    // accessible text by default. Direct DOM query is the pragmatic choice
    // for pure SVG assertions.
    const svg = container.querySelector("svg");
    expect(svg).not.toBeNull();
  });

  it("renders the SVG with width=60 and height=16 as specified by the design", () => {
    const series = [100, 102, 105, 103, 107];
    const { container } = render(
      <SparklineCellRenderer {...makeParams({ ticker: "MSFT", series })} />,
    );
    const svg = container.querySelector("svg");
    // WHY assert width/height: the design spec (PRD-0089 §6.2) pins the SPARK
    // column at 76px wide with a 60×16 SVG. Any change to these dimensions
    // would break the column proportions across all portfolio rows.
    expect(svg?.getAttribute("width")).toBe("60");
    expect(svg?.getAttribute("height")).toBe("16");
  });

  it("renders an em-dash placeholder when the series has fewer than 2 points", () => {
    // Single-point series cannot draw a line — em-dash avoids a broken chart.
    render(
      <SparklineCellRenderer
        {...makeParams({ ticker: "GOOGL", series: [150] })}
      />,
    );
    expect(screen.getByText("—")).toBeInTheDocument();
  });

  it("renders an em-dash placeholder when no series is provided for the ticker", () => {
    // Series map exists but the ticker is not in it — data still loading.
    const params = makeParams({ ticker: "TSLA" });
    // Override context to have a map that doesn't include "TSLA".
    params.context = { holdingsSeries: { OTHER: [100, 101] } };
    render(<SparklineCellRenderer {...params} />);
    expect(screen.getByText("—")).toBeInTheDocument();
  });

  it("renders null for the pinned totals row (no sparkline in TOTAL row)", () => {
    // The pinned-bottom TOTAL row must not show a sparkline — it would be
    // meaningless (aggregate of multiple instruments with incompatible scales).
    const { container } = render(
      <SparklineCellRenderer
        {...makeParams({ ticker: "AAPL", series: [100, 105], isPinned: true })}
      />,
    );
    // A null React return leaves the container completely empty.
    expect(container.firstChild).toBeNull();
  });

  it("renders an em-dash when data prop is undefined (row not yet populated)", () => {
    // This happens during AG Grid's deferred row rendering — data can briefly
    // be undefined before the row data is assigned.
    render(<SparklineCellRenderer {...makeParams({})} />);
    expect(screen.getByText("—")).toBeInTheDocument();
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// SectorAllocationBar tests
// ─────────────────────────────────────────────────────────────────────────────

describe("SectorAllocationBar — stacked horizontal sector bar", () => {
  const sectors: AllocationSlice[] = [
    { label: "Information Technology", value: 50_000, pct: 0.50 },
    { label: "Financials", value: 25_000, pct: 0.25 },
    { label: "Health Care", value: 15_000, pct: 0.15 },
    { label: "Energy", value: 10_000, pct: 0.10 },
  ];

  it("renders one segment per sector", () => {
    const { container } = render(<SectorAllocationBar bySector={sectors} />);
    // WHY not getByText: sector labels are truncated in the bar (4 chars).
    // We count the segments by their title attributes which carry the full label.
    const segments = container.querySelectorAll("[title]");
    // The bar renders one div per sector + the label tease spans (which also use title).
    // We want to verify there is at least one segment per unique label value.
    const titles = Array.from(segments).map((el) => el.getAttribute("title") ?? "");
    // Each segment has a title like "Information Technology: 50.0%"
    expect(titles.some((t) => t.includes("Information Technology"))).toBe(true);
    expect(titles.some((t) => t.includes("Financials"))).toBe(true);
  });

  it("renders segment widths proportional to sector weights", () => {
    const { container } = render(<SectorAllocationBar bySector={sectors} />);
    // All segment divs inside the bar have a `style` with `width: X%`.
    // We collect them and check they match the expected pct values.
    const segmentDivs = container.querySelectorAll("[style*='width']");
    const widths = Array.from(segmentDivs).map((el) => {
      const w = (el as HTMLElement).style.width;
      return parseFloat(w);
    });
    // WHY toBeCloseTo instead of strict equal: floating-point rounding (toFixed(2))
    // can produce 50.00 vs 50.000 etc. toBeCloseTo avoids false failures.
    expect(widths).toContainEqual(expect.closeTo(50.0, 1));
    expect(widths).toContainEqual(expect.closeTo(25.0, 1));
    expect(widths).toContainEqual(expect.closeTo(15.0, 1));
    expect(widths).toContainEqual(expect.closeTo(10.0, 1));
  });

  it("renders the top-3 sector labels in the tease section after the bar", () => {
    render(<SectorAllocationBar bySector={sectors} />);
    // The component shows first 4 chars uppercased of the top-3 sectors.
    // "Information Technology" → "INFO", "Financials" → "FINA", "Health Care" → "HEAL"
    expect(screen.getByText(/INFO/)).toBeInTheDocument();
    expect(screen.getByText(/FINA/)).toBeInTheDocument();
    expect(screen.getByText(/HEAL/)).toBeInTheDocument();
    // 4th sector (Energy) is beyond the top-3 tease limit.
    expect(screen.queryByText(/ENER/)).not.toBeInTheDocument();
  });

  it("renders a fallback em-dash when the sector array is empty", () => {
    render(<SectorAllocationBar bySector={[]} />);
    // WHY screen.getByText("—"): the empty state renders a visible dash.
    // This pins the "no data" UX contract so a future refactor can't silently
    // remove the fallback and leave the strip blank.
    expect(screen.getByText("—")).toBeInTheDocument();
    // The "Sector" label must still appear (strip header is always present).
    expect(screen.getByText("Sector")).toBeInTheDocument();
  });

  it("renders the SECTOR label in the strip header", () => {
    render(<SectorAllocationBar bySector={sectors} />);
    // Case-insensitive: the component uses uppercase tracking CSS, but DOM
    // textContent is still the raw cased value from the source.
    const el = screen.getByText("Sector");
    expect(el).toBeInTheDocument();
  });

  it("sums to 100% when pct values are normalised", () => {
    // Verify segment widths sum to approximately 100% for a normalised input.
    const { container } = render(<SectorAllocationBar bySector={sectors} />);
    const segmentDivs = container.querySelectorAll("[style*='width']");
    const totalWidth = Array.from(segmentDivs).reduce((sum, el) => {
      const w = (el as HTMLElement).style.width;
      return sum + parseFloat(w);
    }, 0);
    // Allow ±1% for floating-point rounding. Sum should be ~100%.
    expect(totalWidth).toBeGreaterThan(99);
    expect(totalWidth).toBeLessThan(101);
  });
});
