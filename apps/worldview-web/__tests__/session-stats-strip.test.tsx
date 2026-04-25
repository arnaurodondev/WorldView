/**
 * __tests__/session-stats-strip.test.tsx — Unit tests for SessionStatsStrip
 *
 * WHY THIS EXISTS: SessionStatsStrip is a pure display component that formats
 * OHLCV data for the instrument detail page. Tests verify:
 * 1. All 5 stat labels (O/H/L/V/VWAP) render with their values
 * 2. Null values show "—" (not 0 or undefined)
 * 3. High value has text-positive class (green)
 * 4. Low value has text-negative class (red)
 * 5. VWAP is conditionally shown
 *
 * WHY NO MOCK: SessionStatsStrip has no external dependencies — pure props → render.
 *
 * DATA SOURCE: Props (parent passes last OHLCV bar data)
 * DESIGN REFERENCE: PRD-0031 §13 SessionStatsStrip, §0.1 Typography, §0.4 Color Discipline
 */

import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { SessionStatsStrip } from "@/components/instrument/SessionStatsStrip";

// ── SessionStatsStrip tests ───────────────────────────────────────────────────

describe("SessionStatsStrip", () => {
  it("renders all 5 stat labels when all values provided", () => {
    render(
      <SessionStatsStrip
        open={170.0}
        high={175.5}
        low={168.25}
        volume={43_200_000}
        vwap={171.8}
      />
    );

    // WHY check labels (not just values): labels confirm the component structure.
    // A typo in "H" vs "L" would cause traders to misread session stats.
    expect(screen.getByText("O")).toBeInTheDocument();
    expect(screen.getByText("H")).toBeInTheDocument();
    expect(screen.getByText("L")).toBeInTheDocument();
    expect(screen.getByText("V")).toBeInTheDocument();
    expect(screen.getByText("VWAP")).toBeInTheDocument();
  });

  it("renders correct price values", () => {
    render(
      <SessionStatsStrip
        open={170.0}
        high={175.5}
        low={168.25}
        volume={43_200_000}
        vwap={171.8}
      />
    );

    // WHY exact value matching: traders rely on correct decimal formatting.
    // "170.00" not "170" — 2 decimal places always shown for price consistency.
    expect(screen.getByText("170.00")).toBeInTheDocument();
    expect(screen.getByText("175.50")).toBeInTheDocument();
    expect(screen.getByText("168.25")).toBeInTheDocument();
    expect(screen.getByText("171.80")).toBeInTheDocument();
  });

  it("renders volume in abbreviated format", () => {
    render(
      <SessionStatsStrip
        open={170.0}
        high={175.5}
        low={168.25}
        volume={43_200_000}
      />
    );

    // WHY abbreviated: full volume "43200000" is unreadable at 11px. "43.20M"
    // matches Bloomberg Terminal display convention for session volume.
    expect(screen.getByText("43.20M")).toBeInTheDocument();
  });

  it("renders em-dash for null open value", () => {
    render(
      <SessionStatsStrip
        open={null}
        high={175.5}
        low={168.25}
        volume={43_200_000}
      />
    );

    // WHY em-dash: null means data not yet available (loading or missing OHLCV bar).
    // Must show "—" not "0" or "null" — 0 would imply an actual price of $0.
    const dashes = screen.getAllByText("—");
    expect(dashes.length).toBeGreaterThanOrEqual(1);
  });

  it("renders em-dash for null high value", () => {
    render(
      <SessionStatsStrip
        open={170.0}
        high={null}
        low={168.25}
        volume={43_200_000}
      />
    );

    const dashes = screen.getAllByText("—");
    expect(dashes.length).toBeGreaterThanOrEqual(1);
  });

  it("renders em-dash for null low value", () => {
    render(
      <SessionStatsStrip
        open={170.0}
        high={175.5}
        low={null}
        volume={43_200_000}
      />
    );

    const dashes = screen.getAllByText("—");
    expect(dashes.length).toBeGreaterThanOrEqual(1);
  });

  it("renders em-dash for null volume", () => {
    render(
      <SessionStatsStrip
        open={170.0}
        high={175.5}
        low={168.25}
        volume={null}
      />
    );

    const dashes = screen.getAllByText("—");
    expect(dashes.length).toBeGreaterThanOrEqual(1);
  });

  it("applies text-positive class to high value span", () => {
    const { container } = render(
      <SessionStatsStrip
        open={170.0}
        high={175.5}
        low={168.25}
        volume={43_200_000}
      />
    );

    // WHY: §0.4 Color Discipline — high = bullish push = text-positive (green).
    // Verifying via class because the color is semantic, not decorative.
    const positiveSpan = container.querySelector(".text-positive");
    expect(positiveSpan).toBeInTheDocument();
    expect(positiveSpan?.textContent).toBe("175.50");
  });

  it("applies text-negative class to low value span", () => {
    const { container } = render(
      <SessionStatsStrip
        open={170.0}
        high={175.5}
        low={168.25}
        volume={43_200_000}
      />
    );

    // WHY: §0.4 Color Discipline — low = bearish push = text-negative (red).
    const negativeSpan = container.querySelector(".text-negative");
    expect(negativeSpan).toBeInTheDocument();
    expect(negativeSpan?.textContent).toBe("168.25");
  });

  it("hides VWAP row when vwap prop is undefined", () => {
    render(
      <SessionStatsStrip
        open={170.0}
        high={175.5}
        low={168.25}
        volume={43_200_000}
        // vwap omitted — should not render VWAP label
      />
    );

    // WHY conditional: VWAP is only available intraday (1H and smaller timeframes).
    // Hiding it for daily bars avoids showing "—" for an optional field.
    expect(screen.queryByText("VWAP")).not.toBeInTheDocument();
  });

  it("hides VWAP row when vwap prop is null", () => {
    render(
      <SessionStatsStrip
        open={170.0}
        high={175.5}
        low={168.25}
        volume={43_200_000}
        vwap={null}
      />
    );

    expect(screen.queryByText("VWAP")).not.toBeInTheDocument();
  });

  it("shows VWAP row when vwap is provided", () => {
    render(
      <SessionStatsStrip
        open={170.0}
        high={175.5}
        low={168.25}
        volume={43_200_000}
        vwap={171.8}
      />
    );

    expect(screen.getByText("VWAP")).toBeInTheDocument();
    expect(screen.getByText("171.80")).toBeInTheDocument();
  });

  it("renders accessibility label on the container", () => {
    render(
      <SessionStatsStrip
        open={170.0}
        high={175.5}
        low={168.25}
        volume={43_200_000}
      />
    );

    // WHY aria-label: screen readers need to announce this as a stats region.
    // "Session statistics" tells the user what the 5 values represent.
    expect(screen.getByLabelText("Session statistics")).toBeInTheDocument();
  });
});
