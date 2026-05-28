/**
 * __tests__/screener/coverage-toggles.test.tsx
 * (PRD-0089 Wave I-B Block IB-L1 · T-IB-03)
 *
 * WHY: pin the two-toggle contract — off-state writes `undefined` (not
 * `false`) so the Wave L-1 backend ignores the field; on-state writes
 * `true` to require coverage. FilterChipStrip auto-renders
 * "Has Fundamentals ✓" / "Has OHLCV ✓" when the flag is true.
 */

import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { CoverageToggles } from "@/features/screener/components/CoverageToggles";
import { FilterChipStrip } from "@/components/screener/FilterChipStrip";
import { DEFAULT_FILTERS } from "@/features/screener/lib/filter-state";

describe("CoverageToggles", () => {
  it("renders both Has Fundamentals + Has OHLCV switches in the off state by default", () => {
    render(
      <CoverageToggles
        hasFundamentals={undefined}
        hasOhlcv={undefined}
        onChange={() => {}}
      />,
    );
    const fundamentals = screen.getByRole("switch", {
      name: /Require fundamentals coverage/i,
    });
    const ohlcv = screen.getByRole("switch", {
      name: /Require OHLCV coverage/i,
    });
    // Radix Switch exposes aria-checked.
    expect(fundamentals).toHaveAttribute("aria-checked", "false");
    expect(ohlcv).toHaveAttribute("aria-checked", "false");
  });

  it("flipping Has Fundamentals ON writes `true` to onChange", () => {
    const onChange = vi.fn();
    render(
      <CoverageToggles
        hasFundamentals={undefined}
        hasOhlcv={undefined}
        onChange={onChange}
      />,
    );
    fireEvent.click(
      screen.getByRole("switch", { name: /Require fundamentals coverage/i }),
    );
    expect(onChange).toHaveBeenCalledWith({ hasFundamentals: true });
  });

  it("flipping Has Fundamentals OFF writes `undefined` (not `false`)", () => {
    // WHY: the Wave L-1 query branches on `is not None`. Writing `false`
    // would actively exclude instruments WITH fundamentals — never desired.
    // The component MUST clear to undefined on toggle-off.
    const onChange = vi.fn();
    render(
      <CoverageToggles
        hasFundamentals={true}
        hasOhlcv={undefined}
        onChange={onChange}
      />,
    );
    fireEvent.click(
      screen.getByRole("switch", { name: /Require fundamentals coverage/i }),
    );
    expect(onChange).toHaveBeenCalledWith({ hasFundamentals: undefined });
  });

  it("Has OHLCV toggle is independent of Has Fundamentals", () => {
    // WHY: regression guard against a copy-paste bug where both toggles
    // share a single onChange branch and clobber each other.
    const onChange = vi.fn();
    render(
      <CoverageToggles
        hasFundamentals={true}
        hasOhlcv={undefined}
        onChange={onChange}
      />,
    );
    fireEvent.click(
      screen.getByRole("switch", { name: /Require OHLCV coverage/i }),
    );
    expect(onChange).toHaveBeenCalledWith({ hasOhlcv: true });
    // Crucially: hasFundamentals was NOT touched.
    expect(onChange.mock.calls[0][0]).not.toHaveProperty("hasFundamentals");
  });
});

describe("FilterChipStrip — coverage chips (T-IB-03)", () => {
  it("renders 'Has Fundamentals ✓' chip when the flag is true", () => {
    render(
      <FilterChipStrip
        filters={{ ...DEFAULT_FILTERS, hasFundamentals: true }}
        onApply={() => {}}
      />,
    );
    expect(screen.getByText(/Has Fundamentals ✓/)).toBeInTheDocument();
  });

  it("renders 'Has OHLCV ✓' chip when the flag is true", () => {
    render(
      <FilterChipStrip
        filters={{ ...DEFAULT_FILTERS, hasOhlcv: true }}
        onApply={() => {}}
      />,
    );
    expect(screen.getByText(/Has OHLCV ✓/)).toBeInTheDocument();
  });

  it("clicking ✕ on a coverage chip clears the flag via onApply", () => {
    const onApply = vi.fn();
    render(
      <FilterChipStrip
        filters={{ ...DEFAULT_FILTERS, hasFundamentals: true, hasOhlcv: true }}
        onApply={onApply}
      />,
    );
    fireEvent.click(
      screen.getByRole("button", {
        name: /Remove filter: Has Fundamentals/i,
      }),
    );
    expect(onApply).toHaveBeenCalledWith(
      expect.objectContaining({ hasFundamentals: undefined, hasOhlcv: true }),
    );
  });

  it("renders no coverage chips when both flags are undefined", () => {
    render(<FilterChipStrip filters={DEFAULT_FILTERS} onApply={() => {}} />);
    expect(screen.queryByText(/Has Fundamentals/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Has OHLCV/)).not.toBeInTheDocument();
  });
});
