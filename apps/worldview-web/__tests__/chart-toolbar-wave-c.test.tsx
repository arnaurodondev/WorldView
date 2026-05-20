/**
 * __tests__/chart-toolbar-wave-c.test.tsx — OBSOLETE after PLAN-0090 T-E-01.
 *
 * WHY THIS FILE IS A SKIP STUB: The original tests asserted behaviour of
 * ChartToolbar's Indicators/Volume dropdowns and the now-deleted DrawingPalette
 * / DrawingCanvas components. PRD-0088 §5 removed the drawing-tools workflow
 * from the Quote tab redesign; PLAN-0090 T-E-01 deletes those components.
 *
 * REPLACEMENT TESTS land in T-E-02 covering the new chart surface:
 *   - OHLCVChart (components/instrument/chart/OHLCVChart.tsx)
 *   - TimeframeToolbar (components/instrument/chart/TimeframeToolbar.tsx)
 *   - createChartSeries / useChartSeries lifecycle
 *
 * Indicator math (computeRSI, computeMACD, ...) lives in instrument-context;
 * if we want to preserve those pure-function tests they should be re-homed in
 * a dedicated `__tests__/instrument-context-indicators.test.ts` file owned by
 * T-E-02.
 *
 * WHY skip rather than delete: per R19 we never delete tests outright.
 */
import { describe, it, expect } from "vitest";

describe.skip("chart-toolbar-wave-c (obsolete — see PLAN-0090 T-E-02)", () => {
  it("placeholder", () => {
    expect(true).toBe(true);
  });
});
