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
  // QA F-006 (2026-05-21): mirror PortfolioSwitcher's try/catch so
  // Safari Private Mode doesn't blow up the entire suite.
  if (typeof window !== "undefined") {
    try {
      window.localStorage.clear();
    } catch {
      /* private mode — no-op */
    }
  }
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
    window.localStorage.setItem("shell.activePortfolioId", "01900000-0000-7000-8000-00000000000a");
    const { result } = renderHook(() => useActivePortfolio(), {
      wrapper: ({ children }) => <ActivePortfolioProvider>{children}</ActivePortfolioProvider>,
    });
    expect(result.current.activePortfolioId).toBe("01900000-0000-7000-8000-00000000000a");
  });

  it("initialActiveId override beats localStorage (test seam)", () => {
    window.localStorage.setItem("shell.activePortfolioId", "01900000-0000-7000-8000-00000000000a");
    const { result } = renderHook(() => useActivePortfolio(), {
      wrapper: ({ children }) =>
        <ActivePortfolioProvider initialActiveId="01900000-0000-7000-8000-00000000000b">{children}</ActivePortfolioProvider>,
    });
    expect(result.current.activePortfolioId).toBe("01900000-0000-7000-8000-00000000000b");
  });

  it("setActivePortfolio writes through to localStorage", () => {
    const { result } = renderHook(() => useActivePortfolio(), {
      wrapper: ({ children }) => <ActivePortfolioProvider initialActiveId={null}>{children}</ActivePortfolioProvider>,
    });
    act(() => result.current.setActivePortfolio("01900000-0000-7000-8000-00000000000c"));
    expect(result.current.activePortfolioId).toBe("01900000-0000-7000-8000-00000000000c");
    expect(window.localStorage.getItem("shell.activePortfolioId")).toBe("01900000-0000-7000-8000-00000000000c");
  });

  it("setting null clears the persisted value (ROOT/All semantics)", () => {
    window.localStorage.setItem("shell.activePortfolioId", "01900000-0000-7000-8000-00000000000d");
    const { result } = renderHook(() => useActivePortfolio(), {
      wrapper: ({ children }) => <ActivePortfolioProvider>{children}</ActivePortfolioProvider>,
    });
    act(() => result.current.setActivePortfolio(null));
    expect(result.current.activePortfolioId).toBeNull();
    expect(window.localStorage.getItem("shell.activePortfolioId")).toBeNull();
  });

  it("(Sec F-001) refuses to persist non-UUID values", () => {
    const { result } = renderHook(() => useActivePortfolio(), {
      wrapper: ({ children }) => <ActivePortfolioProvider initialActiveId={null}>{children}</ActivePortfolioProvider>,
    });
    // In-memory state DOES flip (the noise is in the persistence layer
    // only — UX-wise the call appears to succeed) but localStorage stays
    // empty so a reload resets to null instead of restoring garbage.
    act(() => result.current.setActivePortfolio("not-a-uuid"));
    expect(window.localStorage.getItem("shell.activePortfolioId")).toBeNull();
  });

  it("(Sec F-001) ignores tampered/garbage localStorage on read", () => {
    window.localStorage.setItem("shell.activePortfolioId", "<script>alert(1)</script>");
    const { result } = renderHook(() => useActivePortfolio(), {
      wrapper: ({ children }) => <ActivePortfolioProvider>{children}</ActivePortfolioProvider>,
    });
    // Malformed persisted values are dropped at read; consumer sees null
    // and falls back to portfolios[0] as documented.
    expect(result.current.activePortfolioId).toBeNull();
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
