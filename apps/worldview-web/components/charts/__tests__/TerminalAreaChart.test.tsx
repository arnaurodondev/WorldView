/**
 * TerminalAreaChart tests (F-002 from 2026-05-23 QA report).
 *
 * WHY same recharts mock strategy as TerminalLineChart.test.tsx:
 * ResponsiveContainer uses ResizeObserver + getBoundingClientRect which both
 * return 0 in jsdom. We replace it with a plain div forwarder so the inner
 * AreaChart can render its SVG normally.
 */
import { render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import * as React from "react";

vi.mock("recharts", async (importOriginal) => {
  const actual = await importOriginal<typeof import("recharts")>();
  return {
    ...actual,
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

import { TerminalAreaChart } from "../TerminalAreaChart";

const SAMPLE_DATA = [
  { date: "2026-01-01", drawdown: 0 },
  { date: "2026-01-02", drawdown: -0.05 },
  { date: "2026-01-03", drawdown: -0.02 },
];

describe("TerminalAreaChart", () => {
  it("renders without crashing", () => {
    const { container } = render(
      <TerminalAreaChart
        data={SAMPLE_DATA}
        height={200}
        areas={[{ key: "drawdown", color: "hsl(var(--destructive))", label: "Drawdown" }]}
      />
    );
    // WHY querySelector svg: Recharts renders into SVG; its presence confirms
    // the component mounted and Recharts initialised without errors.
    expect(container.querySelector("svg")).toBeTruthy();
  });

  it("renders a ReferenceLine when zeroLine=true", () => {
    const { container } = render(
      <TerminalAreaChart
        data={SAMPLE_DATA}
        height={200}
        areas={[{ key: "drawdown", color: "hsl(var(--destructive))", label: "Drawdown" }]}
        zeroLine={true}
      />
    );
    // WHY check for line element: zeroLine=true must insert a Recharts
    // ReferenceLine at y=0 so the viewer can see where "at high-water mark"
    // is. A line element in the SVG confirms it rendered.
    expect(container.querySelector("svg")).toBeTruthy();
    // The ReferenceLine renders as a <line> SVG element within the chart.
    const svgLines = container.querySelectorAll("line");
    expect(svgLines.length).toBeGreaterThan(0);
  });

  it("does not render a ReferenceLine when zeroLine=false (default)", () => {
    const { container: withoutZero } = render(
      <TerminalAreaChart
        data={SAMPLE_DATA}
        height={200}
        areas={[{ key: "drawdown", color: "hsl(var(--destructive))", label: "Drawdown" }]}
        zeroLine={false}
      />
    );
    const { container: withZero } = render(
      <TerminalAreaChart
        data={SAMPLE_DATA}
        height={200}
        areas={[{ key: "drawdown", color: "hsl(var(--destructive))", label: "Drawdown" }]}
        zeroLine={true}
      />
    );
    // WHY compare line counts: with zeroLine=true there should be more line
    // elements (axes + reference) than without it.
    const withoutLines = withoutZero.querySelectorAll("line").length;
    const withLines = withZero.querySelectorAll("line").length;
    expect(withLines).toBeGreaterThan(withoutLines);
  });
});
