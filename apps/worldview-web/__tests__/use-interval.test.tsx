/**
 * __tests__/use-interval.test.tsx — PLAN-0059-C C-4 Abramov-pattern timer.
 *
 * COVERS the C-4 critical test:
 *   - test_use_interval_calls_latest_callback
 *     → on each tick the hook calls the LATEST closure it received, not the
 *       one captured at mount. This is the bug the Abramov pattern exists to
 *       prevent; without the savedCallback ref, every tick would call the
 *       closure from the first render forever.
 */

import React, { useState } from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, act } from "@testing-library/react";
import { useInterval } from "@/hooks/useInterval";

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
});

describe("useInterval", () => {
  it("calls the LATEST callback on each tick (Abramov pattern)", () => {
    const calls: number[] = [];

    function Host() {
      const [n, setN] = useState(0);
      // Each render produces a NEW closure that captures the current `n`.
      // A naive setInterval would freeze the first closure (n=0) forever;
      // the savedCallback ref pattern reads `n` at tick time.
      useInterval(() => {
        calls.push(n);
      }, 100);
      return (
        <button data-testid="bump" onClick={() => setN((x) => x + 1)}>
          {n}
        </button>
      );
    }

    const { getByTestId } = render(<Host />);

    // Tick 1 — n is 0.
    act(() => {
      vi.advanceTimersByTime(100);
    });
    expect(calls).toEqual([0]);

    // Bump to n=1, tick again.
    act(() => {
      getByTestId("bump").click();
    });
    act(() => {
      vi.advanceTimersByTime(100);
    });
    expect(calls).toEqual([0, 1]);

    // Bump twice more, then advance one tick — should see n=3.
    act(() => {
      getByTestId("bump").click();
      getByTestId("bump").click();
    });
    act(() => {
      vi.advanceTimersByTime(100);
    });
    expect(calls).toEqual([0, 1, 3]);
  });

  it("delay = null pauses the timer", () => {
    const cb = vi.fn();

    function Host() {
      useInterval(cb, null);
      return null;
    }

    render(<Host />);
    act(() => {
      vi.advanceTimersByTime(5000);
    });
    expect(cb).not.toHaveBeenCalled();
  });

  it("clears the interval on unmount", () => {
    const cb = vi.fn();

    function Host() {
      useInterval(cb, 50);
      return null;
    }

    const { unmount } = render(<Host />);
    act(() => {
      vi.advanceTimersByTime(150);
    });
    const before = cb.mock.calls.length;
    expect(before).toBeGreaterThanOrEqual(2);

    unmount();
    act(() => {
      vi.advanceTimersByTime(500);
    });
    expect(cb.mock.calls.length).toBe(before);
  });
});
