/**
 * components/screener/__tests__/NlScreenerSearch.test.tsx
 *
 * WHY THIS FILE: the NL screen builder maps a backend ScreenerFilter[] back to a
 * FilterState and calls onApply. The risk surface is the WIRING (does submit fire
 * the mutation? does a successful translate apply mapped filters? does an empty
 * result NOT clobber the current screen?). We mock the translate hook so the test
 * is a pure UI-behaviour check with no network / QueryClient plumbing.
 */

import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";

// ── Mock the translate hook ───────────────────────────────────────────────────
// WHY mock the hook (not the gateway): the hook owns the TanStack mutation +
// auth wiring; mocking it keeps this test focused on the component's submit →
// apply behaviour without a QueryClientProvider.
const mutate = vi.fn();
let hookState: {
  mutate: typeof mutate;
  isPending: boolean;
  isError: boolean;
  error: Error | null;
  data: { filters: unknown[]; explanation?: string } | undefined;
};

vi.mock("@/hooks/useNlScreenerTranslate", () => ({
  useNlScreenerTranslate: () => hookState,
}));

import { NlScreenerSearch } from "@/components/screener/NlScreenerSearch";

beforeEach(() => {
  mutate.mockReset();
  hookState = {
    mutate,
    isPending: false,
    isError: false,
    error: null,
    data: undefined,
  };
});

describe("NlScreenerSearch", () => {
  it("does not fire the mutation for an empty / whitespace query", () => {
    render(<NlScreenerSearch onApply={() => {}} />);
    const input = screen.getByLabelText(/describe your screen/i);
    fireEvent.change(input, { target: { value: "   " } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(mutate).not.toHaveBeenCalled();
  });

  it("fires the mutation with the trimmed query on Enter", () => {
    render(<NlScreenerSearch onApply={() => {}} />);
    const input = screen.getByLabelText(/describe your screen/i);
    fireEvent.change(input, { target: { value: "  cheap tech  " } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(mutate).toHaveBeenCalledWith("cheap tech", expect.any(Object));
  });

  it("applies mapped filters on a successful translate with results", () => {
    const onApply = vi.fn();
    // Make mutate invoke its onSuccess callback with a known filter set.
    mutate.mockImplementation((_q, opts) => {
      opts?.onSuccess?.({ filters: [{ metric: "pe_ratio", max_value: 15 }] });
    });
    render(<NlScreenerSearch onApply={onApply} />);
    const input = screen.getByLabelText(/describe your screen/i);
    fireEvent.change(input, { target: { value: "value stocks" } });
    fireEvent.keyDown(input, { key: "Enter" });
    // nlFiltersToFilterState should have produced peMax: 15.
    expect(onApply).toHaveBeenCalledWith(expect.objectContaining({ peMax: 15 }));
  });

  it("does NOT apply (and shows a hint) when translate returns zero filters", () => {
    const onApply = vi.fn();
    mutate.mockImplementation((_q, opts) => {
      opts?.onSuccess?.({ filters: [] });
    });
    render(<NlScreenerSearch onApply={onApply} />);
    const input = screen.getByLabelText(/describe your screen/i);
    fireEvent.change(input, { target: { value: "gibberish" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(onApply).not.toHaveBeenCalled();
    expect(screen.getByText(/couldn.t interpret/i)).toBeInTheDocument();
  });

  it("shows an error message when the mutation errored", () => {
    hookState.isError = true;
    hookState.error = new Error("LLM timeout");
    render(<NlScreenerSearch onApply={() => {}} />);
    expect(screen.getByRole("alert")).toHaveTextContent(/llm timeout/i);
  });

  it("disables input + button while pending", () => {
    hookState.isPending = true;
    render(<NlScreenerSearch onApply={() => {}} />);
    expect(screen.getByLabelText(/describe your screen/i)).toBeDisabled();
    expect(
      screen.getByLabelText(/translate and apply natural-language screen/i),
    ).toBeDisabled();
  });
});
