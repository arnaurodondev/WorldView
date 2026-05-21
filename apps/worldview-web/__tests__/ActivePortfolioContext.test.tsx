/**
 * __tests__/ActivePortfolioContext.test.tsx — PRD-0089 W1.1 F-002.
 *
 * Pins the active-portfolio context contract:
 *   - Lazy init reads localStorage (so the chip's pre-context writes still
 *     load on first mount)
 *   - setActivePortfolio writes through localStorage
 *   - Setting null clears localStorage (ROOT semantics)
 *   - useActivePortfolio outside the provider returns a stable noop, not
 *     throws — keeps usePortfolioMetrics consumable in pre-provider tests
 */

import { describe, it, expect, beforeEach } from "vitest";
import { render, act, renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import {
  ActivePortfolioProvider,
  useActivePortfolio,
} from "@/contexts/ActivePortfolioContext";

beforeEach(() => {
  if (typeof window !== "undefined") window.localStorage.clear();
});

function wrap(children: ReactNode, initialActiveId?: string | null) {
  return (
    <ActivePortfolioProvider initialActiveId={initialActiveId}>
      {children}
    </ActivePortfolioProvider>
  );
}

describe("ActivePortfolioContext", () => {
  it("lazy-inits from localStorage when no initialActiveId override is passed", () => {
    window.localStorage.setItem("shell.activePortfolioId", "p-from-ls");
    const { result } = renderHook(() => useActivePortfolio(), {
      wrapper: ({ children }) => <ActivePortfolioProvider>{children}</ActivePortfolioProvider>,
    });
    expect(result.current.activePortfolioId).toBe("p-from-ls");
  });

  it("initialActiveId override beats localStorage (test seam)", () => {
    window.localStorage.setItem("shell.activePortfolioId", "p-from-ls");
    const { result } = renderHook(() => useActivePortfolio(), {
      wrapper: ({ children }) =>
        <ActivePortfolioProvider initialActiveId="p-override">{children}</ActivePortfolioProvider>,
    });
    expect(result.current.activePortfolioId).toBe("p-override");
  });

  it("setActivePortfolio writes through to localStorage", () => {
    const { result } = renderHook(() => useActivePortfolio(), {
      wrapper: ({ children }) => <ActivePortfolioProvider initialActiveId={null}>{children}</ActivePortfolioProvider>,
    });
    act(() => result.current.setActivePortfolio("p-new"));
    expect(result.current.activePortfolioId).toBe("p-new");
    expect(window.localStorage.getItem("shell.activePortfolioId")).toBe("p-new");
  });

  it("setting null clears the persisted value (ROOT/All semantics)", () => {
    window.localStorage.setItem("shell.activePortfolioId", "p-stale");
    const { result } = renderHook(() => useActivePortfolio(), {
      wrapper: ({ children }) => <ActivePortfolioProvider>{children}</ActivePortfolioProvider>,
    });
    act(() => result.current.setActivePortfolio(null));
    expect(result.current.activePortfolioId).toBeNull();
    expect(window.localStorage.getItem("shell.activePortfolioId")).toBeNull();
  });

  it("useActivePortfolio outside the provider returns a stable noop (does not throw)", () => {
    // No <ActivePortfolioProvider> wrapper — exercise the fallback path.
    const { result, rerender } = renderHook(() => useActivePortfolio());
    expect(result.current.activePortfolioId).toBeNull();
    // setActivePortfolio is a noop but must not throw.
    expect(() => result.current.setActivePortfolio("anything")).not.toThrow();
    // Stable reference across renders so consumers using it in useEffect
    // dependency arrays don't fire on every parent re-render.
    const setterRefBefore = result.current.setActivePortfolio;
    rerender();
    expect(result.current.setActivePortfolio).toBe(setterRefBefore);
  });
});
