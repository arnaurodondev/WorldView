/**
 * TerminalLineChart tests.
 *
 * WHY shallow render over snapshot: we want to assert specific DOM structure
 * (dashed line present) without brittle snapshot churn when Recharts internals change.
 *
 * WHY mock recharts: Recharts' ResponsiveContainer uses ResizeObserver +
 * getBoundingClientRect to determine container dimensions. In jsdom both
 * return zeros, so ResponsiveContainer never renders its children into the
 * DOM — container.querySelector("svg") returns null.
 *
 * The mock replaces ResponsiveContainer with a simple div wrapper (so children
 * render normally) and keeps LineChart/Line/etc. as their real implementations
 * with a fixed width/height. This lets us assert on the SVG structure
 * (stroke-dasharray, presence of paths) without a real browser layout engine.
 *
 * Alternative considered: jsdom ResizeObserver stub + getBoundingClientRect
 * override. That would work but is more brittle — it couples the test to
 * Recharts' internal initialisation order. The mock boundary is cleaner.
 */
import { render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import * as React from "react";

// ── Recharts mock ──────────────────────────────────────────────────────────────
// WHY replace ResponsiveContainer: ResponsiveContainer measures the DOM node via
// ResizeObserver/getBoundingClientRect; both return 0 in jsdom so it never
// mounts its children. Replacing with a simple forwarder that supplies fixed
// width/height to the inner chart lets LineChart render its SVG normally.
vi.mock("recharts", async (importOriginal) => {
  const actual = await importOriginal<typeof import("recharts")>();
  return {
    ...actual,
    // WHY pass width=400/height=200: LineChart reads these dimensions from
    // ResponsiveContainer's render callback. Without them, the SVG is 0x0
    // and Recharts skips rendering. Fixed values are enough for unit tests.
    ResponsiveContainer: ({
      children,
    }: {
      children:
        | React.ReactElement<{ width?: number; height?: number }>
        | ((props: { width: number; height: number }) => React.ReactElement);
    }) => {
      const child =
        typeof children === "function"
          ? children({ width: 400, height: 200 })
          : // eslint-disable-next-line @typescript-eslint/no-explicit-any
            React.cloneElement(children as React.ReactElement<any>, { width: 400, height: 200 });
      return <div data-testid="responsive-container">{child}</div>;
    },
  };
});

import { TerminalLineChart } from "../TerminalLineChart";

const SAMPLE_DATA = [
  { date: "2026-01-01", portfolio: 0.05, spy: 0.03 },
  { date: "2026-01-02", portfolio: 0.08, spy: 0.04 },
  { date: "2026-01-03", portfolio: 0.06, spy: 0.05 },
];

describe("TerminalLineChart", () => {
  it("renders without crashing", () => {
    const { container } = render(
      <TerminalLineChart
        data={SAMPLE_DATA}
        lines={[
          { key: "portfolio", color: "#FFD60A" },
          { key: "spy", color: "#888", dashed: true },
        ]}
        height={200}
      />
    );
    // WHY querySelector svg: Recharts renders into an SVG; its presence confirms
    // the component mounted and Recharts initialised without errors.
    expect(container.querySelector("svg")).toBeTruthy();
  });

  it("applies strokeDasharray when dashed=true", () => {
    const { container } = render(
      <TerminalLineChart
        data={SAMPLE_DATA}
        lines={[{ key: "portfolio", color: "#FFD60A", dashed: true }]}
        height={200}
      />
    );
    // WHY check attribute directly: the dashed prop must translate to a
    // strokeDasharray SVG attribute on the path element — this is the contract
    // consumers depend on for visual distinction between series.
    const paths = container.querySelectorAll("path[stroke-dasharray]");
    expect(paths.length).toBeGreaterThan(0);
  });
});
