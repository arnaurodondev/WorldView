/**
 * __tests__/RefreshAllButton.test.tsx — global refresh trigger contract.
 *
 * Pins that clicking the button calls queryClient.invalidateQueries() —
 * the entire reason this component exists.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, act } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { RefreshAllButton } from "@/components/shell/RefreshAllButton";

function wrapper(client: QueryClient) {
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
}

beforeEach(() => {
  // F-QA-07: control the spinner-reset timer deterministically.
  vi.useFakeTimers();
});
afterEach(() => {
  vi.useRealTimers();
});

describe("RefreshAllButton", () => {
  it("calls queryClient.invalidateQueries with predicate when clicked", () => {
    const client = new QueryClient();
    const spy = vi.spyOn(client, "invalidateQueries");
    render(<RefreshAllButton />, { wrapper: wrapper(client) });

    fireEvent.click(screen.getByRole("button", { name: /refresh all dashboard data/i }));
    expect(spy).toHaveBeenCalledTimes(1);
    // F-QA-04 fix: must pass a predicate, not an undefined "invalidate everything" call.
    const callArg = spy.mock.calls[0]?.[0];
    expect(callArg).toBeDefined();
    expect(typeof callArg?.predicate).toBe("function");
  });

  it("predicate filters by query-key allowlist (F-QA-04)", () => {
    const client = new QueryClient();
    const spy = vi.spyOn(client, "invalidateQueries");
    render(<RefreshAllButton />, { wrapper: wrapper(client) });
    fireEvent.click(screen.getByRole("button", { name: /refresh all dashboard data/i }));

    const predicate = spy.mock.calls[0]?.[0]?.predicate;
    if (!predicate) throw new Error("predicate missing");
    // Allowlisted keys → true
    expect(predicate({ queryKey: ["holdings-quotes", []] } as never)).toBe(true);
    expect(predicate({ queryKey: ["dashboard-prediction-markets"] } as never)).toBe(true);
    expect(predicate({ queryKey: ["portfolios"] } as never)).toBe(true);
    // Streaming keys → false (the whole point of the fix)
    expect(predicate({ queryKey: ["alert-stream"] } as never)).toBe(false);
    expect(predicate({ queryKey: ["chat-stream"] } as never)).toBe(false);
    // Unknown shape → false
    expect(predicate({ queryKey: [123] } as never)).toBe(false);
  });

  it("toggles the spinning class for 600ms after click (F-QA-07)", () => {
    const client = new QueryClient();
    render(<RefreshAllButton />, { wrapper: wrapper(client) });
    const btn = screen.getByRole("button", { name: /refresh all dashboard data/i });
    const icon = () => btn.querySelector("svg");

    expect(icon()?.classList.contains("animate-spin")).toBe(false);

    act(() => {
      fireEvent.click(btn);
    });
    expect(icon()?.classList.contains("animate-spin")).toBe(true);

    // Advance past the 600ms reset.
    act(() => {
      vi.advanceTimersByTime(700);
    });
    expect(icon()?.classList.contains("animate-spin")).toBe(false);
  });

  it("does not leak the spinner timer when unmounted mid-spin (F-QA-02)", () => {
    const client = new QueryClient();
    const errSpy = vi.spyOn(console, "error").mockImplementation(() => {});

    const { unmount } = render(<RefreshAllButton />, { wrapper: wrapper(client) });
    const btn = screen.getByRole("button", { name: /refresh all dashboard data/i });
    act(() => {
      fireEvent.click(btn);
    });
    // Unmount BEFORE the 600ms timer fires — the cleanup effect must clear it.
    unmount();
    act(() => {
      vi.advanceTimersByTime(1000);
    });
    // No "Can't perform a React state update on an unmounted component" warning.
    expect(errSpy).not.toHaveBeenCalled();
    errSpy.mockRestore();
  });
});
