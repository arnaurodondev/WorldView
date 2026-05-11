/**
 * __tests__/destructive-button.test.tsx — 3-tier confirm ladder.
 */

import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, fireEvent, act } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { DestructiveButton } from "@/components/ui/destructive-button";

afterEach(() => {
  // WHY: any test that calls vi.useFakeTimers() must restore real timers
  // BEFORE the next test starts, or userEvent (which awaits real microtasks)
  // hangs. Restoring in afterEach is fail-safe.
  vi.useRealTimers();
});

describe("DestructiveButton T1 (inline two-step)", () => {
  it("requires two clicks before firing onConfirm", () => {
    const onConfirm = vi.fn();
    render(
      <DestructiveButton tier="t1" onConfirm={onConfirm}>
        Dismiss
      </DestructiveButton>,
    );

    const btn = screen.getByRole("button", { name: /dismiss/i });
    fireEvent.click(btn);
    expect(onConfirm).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: /confirm\?/i })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /confirm\?/i }));
    expect(onConfirm).toHaveBeenCalledTimes(1);
  });

  it("reverts to original label after timeout", () => {
    vi.useFakeTimers();
    const onConfirm = vi.fn();
    render(
      <DestructiveButton tier="t1" onConfirm={onConfirm}>
        Dismiss
      </DestructiveButton>,
    );
    fireEvent.click(screen.getByRole("button", { name: /dismiss/i }));
    expect(screen.getByRole("button", { name: /confirm\?/i })).toBeInTheDocument();

    // WHY act + advanceTimers: with fake timers we have to flush React effects
    // synchronously inside act(). waitFor uses real-time setInterval and would
    // hang forever under fake timers.
    act(() => {
      vi.advanceTimersByTime(4100);
    });

    expect(screen.getByRole("button", { name: /dismiss/i })).toBeInTheDocument();
    expect(onConfirm).not.toHaveBeenCalled();
  });
});

describe("DestructiveButton T3 (type-to-confirm)", () => {
  it("disables confirm until the user types the exact phrase", async () => {
    const user = userEvent.setup();
    const onConfirm = vi.fn();
    render(
      <DestructiveButton
        tier="t3"
        onConfirm={onConfirm}
        confirmTitle="Delete portfolio?"
        typeToConfirm="My Portfolio"
      >
        Delete
      </DestructiveButton>,
    );

    await user.click(screen.getByRole("button", { name: /delete$/i }));
    const input = await screen.findByLabelText(/type to confirm/i);
    // Dialog action button is the LAST "Delete" — trigger button still in DOM.
    const allDeletes = screen.getAllByRole("button", { name: /^delete$/i });
    const confirm = allDeletes[allDeletes.length - 1]!;
    expect(confirm).toBeDisabled();

    await user.type(input, "wrong");
    expect(confirm).toBeDisabled();
    await user.clear(input);

    await user.type(input, "My Portfolio");
    expect(confirm).not.toBeDisabled();
    await user.click(confirm);
    expect(onConfirm).toHaveBeenCalledTimes(1);
  });
});
