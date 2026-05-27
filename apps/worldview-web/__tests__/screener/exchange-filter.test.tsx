/**
 * __tests__/screener/exchange-filter.test.tsx
 * (PRD-0089 Wave I-B Block IB-L1 · T-IB-02)
 *
 * WHY: pin the Exchange row contract — multi-select combobox over the
 * static COMMON_EXCHANGES list, FilterChipStrip auto-renders
 * "Exchange: NYSE, NASDAQ ×" whenever exchanges.length > 0, ✕ clears
 * via onApply. Mirror of country-filter tests minus the regional preset
 * chip behaviour (exchanges have no clusters worth chipping).
 */

import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { ExchangeFilterRow } from "@/features/screener/components/ExchangeFilterRow";
import { FilterChipStrip } from "@/components/screener/FilterChipStrip";
import { DEFAULT_FILTERS } from "@/features/screener/lib/filter-state";
import { COMMON_EXCHANGES } from "@/lib/screener/exchanges";

describe("ExchangeFilterRow", () => {
  it("renders the Exchange label and a MultiCombobox with the static list", () => {
    // WHY label assertion: the popover relies on the 10px uppercase label
    // for scannability — a missing label would orphan the row visually.
    render(<ExchangeFilterRow value={[]} onChange={() => {}} />);
    expect(screen.getByText("Exchange")).toBeInTheDocument();
    // MultiCombobox renders a trigger Button with the placeholder copy.
    expect(
      screen.getByRole("button", { name: /All exchanges/i }),
    ).toBeInTheDocument();
  });

  it("renders backend-truncation badge when more than one exchange is selected", () => {
    // WHY: QA #3 — Wave L-1 backend takes only `[0]` of the exchanges
    // multi-select. The badge surfaces this silent drop at selection time.
    render(<ExchangeFilterRow value={["NYSE", "NASDAQ"]} onChange={() => {}} />);
    expect(screen.getByText("backend: 1 of 2")).toBeInTheDocument();
  });

  it("does not render the truncation badge when one or zero exchanges are selected", () => {
    // WHY: badge must not appear when nothing is being truncated — otherwise
    // it would falsely imply the backend is dropping data.
    const { rerender } = render(
      <ExchangeFilterRow value={[]} onChange={() => {}} />,
    );
    expect(screen.queryByText(/backend: 1 of/)).not.toBeInTheDocument();
    rerender(<ExchangeFilterRow value={["NYSE"]} onChange={() => {}} />);
    expect(screen.queryByText(/backend: 1 of/)).not.toBeInTheDocument();
  });

  it("static option list contains the major exchanges (NYSE, NASDAQ, LSE, JPX)", () => {
    // WHY: regression guard against silent edits to the static fallback —
    // dropping a major exchange would invisibly break screens for users
    // until a future allowlist-hook flip surfaces it.
    expect(COMMON_EXCHANGES).toContain("NYSE");
    expect(COMMON_EXCHANGES).toContain("NASDAQ");
    expect(COMMON_EXCHANGES).toContain("LSE");
    expect(COMMON_EXCHANGES).toContain("JPX");
  });
});

describe("FilterChipStrip — exchange chip propagation (T-IB-02)", () => {
  it("renders one chip 'Exchange: NYSE, NASDAQ' for a two-entry selection", () => {
    render(
      <FilterChipStrip
        filters={{ ...DEFAULT_FILTERS, exchanges: ["NYSE", "NASDAQ"] }}
        onApply={() => {}}
      />,
    );
    expect(screen.getByText("Exchange: NYSE, NASDAQ")).toBeInTheDocument();
  });

  it("clicking ✕ on the exchange chip clears via onApply", () => {
    const onApply = vi.fn();
    render(
      <FilterChipStrip
        filters={{ ...DEFAULT_FILTERS, exchanges: ["NYSE"] }}
        onApply={onApply}
      />,
    );
    fireEvent.click(
      screen.getByRole("button", { name: /Remove filter: Exchange: NYSE/i }),
    );
    expect(onApply).toHaveBeenCalledWith(
      expect.objectContaining({ exchanges: undefined }),
    );
  });

  it("renders no chip when exchanges is undefined or empty", () => {
    const { rerender } = render(
      <FilterChipStrip filters={DEFAULT_FILTERS} onApply={() => {}} />,
    );
    expect(screen.queryByText(/Exchange:/)).not.toBeInTheDocument();
    rerender(
      <FilterChipStrip
        filters={{ ...DEFAULT_FILTERS, exchanges: [] }}
        onApply={() => {}}
      />,
    );
    expect(screen.queryByText(/Exchange:/)).not.toBeInTheDocument();
  });
});
