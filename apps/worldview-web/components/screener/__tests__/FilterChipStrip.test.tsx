/**
 * components/screener/__tests__/FilterChipStrip.test.tsx
 * (PRD-0089 Wave I)
 *
 * WHY THIS EXISTS: FilterChipStrip is the primary filter-state summary surface —
 * it governs what chips the analyst sees and whether removing one correctly
 * updates the filter state. These tests pin both the render contract (chips
 * appear for active filters) and the mutation contract (× removes the right key).
 *
 * WHAT WE TEST:
 *   1. No chips rendered when filters are at DEFAULT_FILTERS.
 *   2. A chip appears for each active numeric filter (min and max separately).
 *   3. Clicking × on a chip calls onApply with that filter key deleted.
 *   4. The "+ Add filter" button is always present.
 *   5. "Reset" button only renders when chips are active.
 *   6. onReset is called when Reset is clicked.
 *   7. onSave button visibility matches prop presence.
 *   8. Dividend yield filter renders with % conversion.
 *
 * DEBOUNCE: FilterChipStrip debounces onApply 250ms.
 * Tests that verify onApply use fake timers and fireEvent (not userEvent.click)
 * to avoid Radix UI focus-trap / pointer-event deadlocks with jsdom.
 */

import { describe, expect, it, vi, afterEach } from "vitest";
import { render, screen, fireEvent, act } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { FilterChipStrip } from "@/components/screener/FilterChipStrip";
import { DEFAULT_FILTERS, type FilterState } from "@/features/screener/lib/filter-state";

// ── Helpers ────────────────────────────────────────────────────────────────────

afterEach(() => {
  // Reset fake timers after each test to avoid bleed-through.
  vi.useRealTimers();
});

/**
 * makeFilters — merge DEFAULT_FILTERS with override.
 * WHY: keeps tests concise; tests only declare what differs from the default.
 */
function makeFilters(override: Partial<FilterState>): FilterState {
  return { ...DEFAULT_FILTERS, ...override };
}

// ── Tests ─────────────────────────────────────────────────────────────────────

describe("FilterChipStrip", () => {
  it("renders no chips when filters are at defaults", () => {
    render(
      <FilterChipStrip
        appliedFilters={DEFAULT_FILTERS}
        onApply={() => {}}
      />,
    );
    // The only interactive element in the empty state is "+ Add filter"
    expect(screen.getByRole("button", { name: /add a filter/i })).toBeInTheDocument();
    // No × buttons (no chips to remove)
    expect(screen.queryByRole("button", { name: /remove filter/i })).not.toBeInTheDocument();
  });

  it("renders a chip for a max P/E filter", () => {
    render(
      <FilterChipStrip
        appliedFilters={makeFilters({ peMax: 15 })}
        onApply={() => {}}
      />,
    );
    // Chip label: "P/E < 15" (lt operator, display as raw number)
    expect(screen.getByText(/P\/E < 15/i)).toBeInTheDocument();
  });

  it("renders a chip for a min ROE% filter (decimal to % conversion)", () => {
    // roe stored as decimal: 0.15 = 15%
    render(
      <FilterChipStrip
        appliedFilters={makeFilters({ roeMin: 0.15 })}
        onApply={() => {}}
      />,
    );
    // Chip label: "ROE% > 15.0%"
    expect(screen.getByText(/ROE% > 15\.0%/i)).toBeInTheDocument();
  });

  it("renders separate chips for min and max on the same field", () => {
    render(
      <FilterChipStrip
        appliedFilters={makeFilters({ peMin: 5, peMax: 25 })}
        onApply={() => {}}
      />,
    );
    expect(screen.getByText(/P\/E > 5/i)).toBeInTheDocument();
    expect(screen.getByText(/P\/E < 25/i)).toBeInTheDocument();
  });

  it("calls onApply with the filter key removed when × is clicked (debounced)", () => {
    const onApply = vi.fn();
    // WHY fake timers: FilterChipStrip debounces 250ms before firing onApply.
    // WHY fireEvent (not userEvent.click): Radix UI Popover inside the same
    // component tree sets up focus traps. userEvent.click runs pointer
    // event simulation that can deadlock with Radix's jsdom focus management.
    // fireEvent.click skips pointer events entirely and is safe here — we're
    // testing the remove button, not the popover open trigger.
    vi.useFakeTimers();

    render(
      <FilterChipStrip
        appliedFilters={makeFilters({ peMax: 15 })}
        onApply={onApply}
      />,
    );

    // Click the × button on the P/E < 15 chip via fireEvent (skips pointer dance)
    const removeBtn = screen.getByRole("button", { name: /remove filter.*P\/E < 15/i });
    fireEvent.click(removeBtn);

    // Not called yet — debounce hasn't fired
    expect(onApply).not.toHaveBeenCalled();

    // Advance past the 250ms debounce
    act(() => {
      vi.advanceTimersByTime(300);
    });

    expect(onApply).toHaveBeenCalledTimes(1);
    const calledWith = onApply.mock.calls[0][0] as FilterState;
    // The peMax key should be absent (deleted, not set to undefined)
    expect("peMax" in calledWith).toBe(false);
  });

  it("batches multiple rapid chip removes into one onApply call (debounce)", () => {
    const onApply = vi.fn();
    vi.useFakeTimers();

    render(
      <FilterChipStrip
        appliedFilters={makeFilters({ peMax: 15, pbMax: 2 })}
        onApply={onApply}
      />,
    );

    // Remove both chips rapidly — should still produce only one onApply call
    fireEvent.click(screen.getByRole("button", { name: /remove filter.*P\/E < 15/i }));
    fireEvent.click(screen.getByRole("button", { name: /remove filter.*P\/B < 2/i }));

    act(() => {
      vi.advanceTimersByTime(300);
    });

    // WHY 1 call (not 2): the debounce timer resets on each action; only the
    // last state snapshot fires. This is the Bloomberg EQS debounce pattern.
    expect(onApply).toHaveBeenCalledTimes(1);
  });

  it("shows the Reset button only when chips are present", () => {
    const { rerender } = render(
      <FilterChipStrip
        appliedFilters={DEFAULT_FILTERS}
        onApply={() => {}}
        onReset={() => {}}
      />,
    );
    // No chips → no Reset (don't offer a button that does nothing)
    expect(screen.queryByRole("button", { name: /^reset$/i })).not.toBeInTheDocument();

    rerender(
      <FilterChipStrip
        appliedFilters={makeFilters({ peMax: 15 })}
        onApply={() => {}}
        onReset={() => {}}
      />,
    );
    // Chips present → Reset is visible
    expect(screen.getByRole("button", { name: /^reset$/i })).toBeInTheDocument();
  });

  it("calls onReset synchronously when Reset button is clicked", () => {
    // WHY fireEvent (not userEvent): same Radix/pointer-event deadlock concern.
    // onReset is synchronous — no debounce needed.
    const onReset = vi.fn();
    render(
      <FilterChipStrip
        appliedFilters={makeFilters({ peMax: 15 })}
        onApply={() => {}}
        onReset={onReset}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /^reset$/i }));
    expect(onReset).toHaveBeenCalledTimes(1);
  });

  it("renders the Save button only when onSave is provided", () => {
    const { rerender } = render(
      <FilterChipStrip
        appliedFilters={DEFAULT_FILTERS}
        onApply={() => {}}
      />,
    );
    // No onSave → no Save button
    expect(screen.queryByRole("button", { name: /save/i })).not.toBeInTheDocument();

    rerender(
      <FilterChipStrip
        appliedFilters={DEFAULT_FILTERS}
        onApply={() => {}}
        onSave={() => {}}
      />,
    );
    expect(screen.getByRole("button", { name: /save/i })).toBeInTheDocument();
  });

  it("renders a chip for a dividend yield filter (% display)", () => {
    // divYieldMin: 0.02 = 2%; chip should show "DIV Y% > 2.0%"
    render(
      <FilterChipStrip
        appliedFilters={makeFilters({ divYieldMin: 0.02 })}
        onApply={() => {}}
      />,
    );
    expect(screen.getByText(/DIV Y% > 2\.0%/i)).toBeInTheDocument();
  });

  it("renders a chip for a forward P/E max filter", () => {
    render(
      <FilterChipStrip
        appliedFilters={makeFilters({ forwardPeMax: 20 })}
        onApply={() => {}}
      />,
    );
    expect(screen.getByText(/FWD P\/E < 20/i)).toBeInTheDocument();
  });
});
